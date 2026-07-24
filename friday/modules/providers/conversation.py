"""Conversation history management for the Unified AI Engine.

This module provides conversation history management that maintains a single
conversation history across provider switches, tags messages with provider/model
metadata, and includes relevant history in new provider contexts.

Features:
- Single conversation history across provider switches (Requirement 14.1)
- Provider/model tagging for each message (Requirement 14.3)
- History inclusion in new provider context (Requirement 14.2)
- View which model generated each response (Requirement 14.4)

Requirements: 13.3, 14.1, 14.2, 14.3, 14.4
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from friday.modules.providers.models import FridayMessage


@dataclass
class ConversationHistoryManager:
    """Manages conversation history across provider switches.
    
    Maintains a single conversation history per session, regardless of which
    provider generates responses. Each message is tagged with the provider
    and model that generated it, allowing users to see which model produced
    each response.
    
    Attributes:
        _histories: Dictionary mapping session_id to list of FridayMessage objects
        _max_history_length: Maximum messages to keep per session (default: 100)
    
    Requirements: 13.3, 14.1, 14.2, 14.3, 14.4
    """
    
    _histories: dict[str, list[FridayMessage]] = field(default_factory=dict)
    _max_history_length: int = 100
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        name: Optional[str] = None,
        tool_call_id: Optional[str] = None,
    ) -> FridayMessage:
        """Add a message to the conversation history.
        
        Creates a new FridayMessage with the provided content and metadata,
        including provider and model information for assistant messages.
        
        Args:
            session_id: Session identifier for the conversation
            role: Message role ('system', 'user', 'assistant', 'tool')
            content: The message content
            provider: Provider that generated this message (for assistant messages)
            model: Model that generated this message (for assistant messages)
            name: Tool name for tool messages
            tool_call_id: ID of the tool call this message responds to
            
        Returns:
            The created FridayMessage object
            
        Requirements: 14.1, 14.3
        """
        # Initialize history for this session if needed
        if session_id not in self._histories:
            self._histories[session_id] = []
        
        # Create the message with timestamp
        message = FridayMessage(
            role=role,
            content=content,
            provider=provider,
            model=model,
            name=name,
            tool_call_id=tool_call_id,
            timestamp=datetime.utcnow().isoformat() + "Z",
        )
        
        # Add to history
        self._histories[session_id].append(message)
        
        # Trim history if it exceeds max length
        if len(self._histories[session_id]) > self._max_history_length:
            # Keep the most recent messages, but preserve system messages
            history = self._histories[session_id]
            system_messages = [m for m in history if m.role == "system"]
            non_system = [m for m in history if m.role != "system"]
            
            # Keep last N-len(system_messages) non-system messages
            keep_count = self._max_history_length - len(system_messages)
            trimmed_non_system = non_system[-keep_count:] if keep_count > 0 else []
            
            self._histories[session_id] = system_messages + trimmed_non_system
        
        return message
    
    def add_user_message(
        self,
        session_id: str,
        content: str,
    ) -> FridayMessage:
        """Add a user message to the conversation history.
        
        Convenience method for adding user messages without provider metadata.
        
        Args:
            session_id: Session identifier for the conversation
            content: The user's message content
            
        Returns:
            The created FridayMessage object
        """
        return self.add_message(
            session_id=session_id,
            role="user",
            content=content,
        )
    
    def add_assistant_message(
        self,
        session_id: str,
        content: str,
        provider: str,
        model: str,
    ) -> FridayMessage:
        """Add an assistant message to the conversation history.
        
        Tags the message with the provider and model that generated it,
        fulfilling Requirement 14.3.
        
        Args:
            session_id: Session identifier for the conversation
            content: The assistant's message content
            provider: Provider that generated this message
            model: Model that generated this message
            
        Returns:
            The created FridayMessage object
            
        Requirements: 14.3
        """
        return self.add_message(
            session_id=session_id,
            role="assistant",
            content=content,
            provider=provider,
            model=model,
        )
    
    def add_system_message(
        self,
        session_id: str,
        content: str,
    ) -> FridayMessage:
        """Add a system message to the conversation history.
        
        Args:
            session_id: Session identifier for the conversation
            content: The system message content
            
        Returns:
            The created FridayMessage object
        """
        return self.add_message(
            session_id=session_id,
            role="system",
            content=content,
        )
    
    def add_tool_message(
        self,
        session_id: str,
        content: str,
        name: str,
        tool_call_id: str,
    ) -> FridayMessage:
        """Add a tool response message to the conversation history.
        
        Args:
            session_id: Session identifier for the conversation
            content: The tool response content
            name: Name of the tool
            tool_call_id: ID of the tool call this responds to
            
        Returns:
            The created FridayMessage object
        """
        return self.add_message(
            session_id=session_id,
            role="tool",
            content=content,
            name=name,
            tool_call_id=tool_call_id,
        )
    
    def get_history(
        self,
        session_id: str,
        limit: Optional[int] = None,
    ) -> list[FridayMessage]:
        """Get the conversation history for a session.
        
        Returns the full conversation history, maintaining order across
        provider switches. This fulfills Requirement 14.1 by providing
        a single unified history.
        
        Args:
            session_id: Session identifier for the conversation
            limit: Optional maximum number of messages to return (most recent)
            
        Returns:
            List of FridayMessage objects in chronological order
            
        Requirements: 14.1
        """
        history = self._histories.get(session_id, [])
        
        if limit is not None and limit > 0 and len(history) > limit:
            # Keep system messages and the most recent non-system messages
            system_messages = [m for m in history if m.role == "system"]
            non_system = [m for m in history if m.role != "system"]
            
            keep_count = limit - len(system_messages)
            if keep_count > 0:
                return system_messages + non_system[-keep_count:]
            return system_messages[:limit]
        
        return list(history)
    
    def get_history_as_dicts(
        self,
        session_id: str,
        limit: Optional[int] = None,
        include_metadata: bool = False,
    ) -> list[dict[str, Any]]:
        """Get the conversation history as dictionaries.
        
        Converts FridayMessage objects to dictionaries suitable for
        sending to AI providers. Can optionally include provider/model
        metadata for UI display (Requirement 14.4).
        
        Args:
            session_id: Session identifier for the conversation
            limit: Optional maximum number of messages to return
            include_metadata: If True, include provider/model metadata
            
        Returns:
            List of message dictionaries
            
        Requirements: 14.2, 14.4
        """
        history = self.get_history(session_id, limit)
        
        result = []
        for msg in history:
            msg_dict: dict[str, Any] = {
                "role": msg.role,
                "content": msg.content,
            }
            
            # Include name for tool messages
            if msg.name:
                msg_dict["name"] = msg.name
            
            # Include tool_call_id for tool messages
            if msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            
            # Include metadata if requested (for UI display)
            if include_metadata:
                if msg.provider:
                    msg_dict["provider"] = msg.provider
                if msg.model:
                    msg_dict["model"] = msg.model
                if msg.timestamp:
                    msg_dict["timestamp"] = msg.timestamp
            
            result.append(msg_dict)
        
        return result
    
    def get_messages_for_provider(
        self,
        session_id: str,
        max_messages: Optional[int] = None,
    ) -> list[dict[str, str]]:
        """Get messages formatted for sending to a provider.
        
        Returns the conversation history in the standard format expected
        by AI providers (role and content only), excluding metadata.
        This is used when including history in a new provider's context
        after a provider switch (Requirement 14.2).
        
        Args:
            session_id: Session identifier for the conversation
            max_messages: Optional maximum number of messages to include
            
        Returns:
            List of message dictionaries with role and content
            
        Requirements: 14.2
        """
        return self.get_history_as_dicts(
            session_id=session_id,
            limit=max_messages,
            include_metadata=False,
        )
    
    def get_messages_with_model_info(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Get messages with model information for UI display.
        
        Returns the conversation history with provider and model metadata
        included, allowing users to view which model generated each response.
        This fulfills Requirement 14.4.
        
        Args:
            session_id: Session identifier for the conversation
            
        Returns:
            List of message dictionaries including provider/model metadata
            
        Requirements: 14.4
        """
        return self.get_history_as_dicts(
            session_id=session_id,
            include_metadata=True,
        )
    
    def clear_history(self, session_id: str) -> None:
        """Clear the conversation history for a session.
        
        Removes all messages from the specified session's history.
        
        Args:
            session_id: Session identifier for the conversation
        """
        if session_id in self._histories:
            del self._histories[session_id]
    
    def has_history(self, session_id: str) -> bool:
        """Check if a session has any conversation history.
        
        Args:
            session_id: Session identifier to check
            
        Returns:
            True if the session has history, False otherwise
        """
        return session_id in self._histories and len(self._histories[session_id]) > 0
    
    def get_session_count(self) -> int:
        """Get the number of active sessions with history.
        
        Returns:
            Number of sessions with conversation history
        """
        return len(self._histories)
    
    def get_message_count(self, session_id: str) -> int:
        """Get the number of messages in a session's history.
        
        Args:
            session_id: Session identifier to check
            
        Returns:
            Number of messages in the session's history
        """
        return len(self._histories.get(session_id, []))
    
    def get_last_provider(self, session_id: str) -> Optional[str]:
        """Get the provider that generated the last assistant message.
        
        Useful for tracking which provider was last used in a conversation.
        
        Args:
            session_id: Session identifier to check
            
        Returns:
            Provider name or None if no assistant messages exist
        """
        history = self._histories.get(session_id, [])
        for msg in reversed(history):
            if msg.role == "assistant" and msg.provider:
                return msg.provider
        return None
    
    def get_last_model(self, session_id: str) -> Optional[str]:
        """Get the model that generated the last assistant message.
        
        Useful for tracking which model was last used in a conversation.
        
        Args:
            session_id: Session identifier to check
            
        Returns:
            Model name or None if no assistant messages exist
        """
        history = self._histories.get(session_id, [])
        for msg in reversed(history):
            if msg.role == "assistant" and msg.model:
                return msg.model
        return None
    
    def get_provider_usage(self, session_id: str) -> dict[str, int]:
        """Get a count of messages generated by each provider.
        
        Useful for showing users how many responses came from each provider.
        
        Args:
            session_id: Session identifier to check
            
        Returns:
            Dictionary mapping provider names to message counts
        """
        history = self._histories.get(session_id, [])
        usage: dict[str, int] = {}
        
        for msg in history:
            if msg.role == "assistant" and msg.provider:
                usage[msg.provider] = usage.get(msg.provider, 0) + 1
        
        return usage
