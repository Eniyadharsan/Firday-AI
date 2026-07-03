/**
 * JARVIS Mobile App
 *
 * Personal AI assistant with voice conversation.
 * Connects to your JARVIS server for AI responses.
 * Works on iPhone, Android, and Web.
 */

import React, { useState, useRef, useEffect } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, ScrollView,
  StyleSheet, StatusBar, Animated, KeyboardAvoidingView, Platform,
  Alert,
} from 'react-native';
import * as Speech from 'expo-speech';
import { Ionicons } from '@expo/vector-icons';

// ======= CONFIGURE YOUR SERVER URL HERE =======
// Change this to your PC's IP or public URL
const SERVER_URL = 'http://192.168.26.21:3000';
// ===============================================

interface Message {
  id: string;
  text: string;
  role: 'user' | 'assistant';
  timestamp: Date;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [token, setToken] = useState('');
  const [authMode, setAuthMode] = useState<'check' | 'setup' | 'login'>('check');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const scrollRef = useRef<ScrollView>(null);
  const pulseAnim = useRef(new Animated.Value(1)).current;

  // Orb pulse animation
  useEffect(() => {
    if (isSpeaking) {
      Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, { toValue: 1.15, duration: 600, useNativeDriver: true }),
          Animated.timing(pulseAnim, { toValue: 1, duration: 600, useNativeDriver: true }),
        ])
      ).start();
    } else {
      pulseAnim.setValue(1);
    }
  }, [isSpeaking]);

  // Check auth status on mount
  useEffect(() => {
    checkAuth();
  }, []);

  async function checkAuth() {
    try {
      const res = await fetch(`${SERVER_URL}/auth/status`);
      const data = await res.json();
      setAuthMode(data.needsSetup ? 'setup' : 'login');
    } catch {
      Alert.alert('Connection Error', `Can't reach JARVIS at ${SERVER_URL}. Make sure the server is running.`);
    }
  }

  async function handleAuth() {
    if (!input.trim()) return;
    const password = input.trim();
    setInput('');

    const endpoint = authMode === 'setup' ? '/auth/setup' : '/auth/login';
    try {
      const res = await fetch(`${SERVER_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });
      const data = await res.json();
      if (data.token) {
        setToken(data.token);
        setIsLoggedIn(true);
        addMessage("Unlocked. How can I help you today?", 'assistant');
        speak("Unlocked. How can I help you today?");
      } else {
        Alert.alert('Error', data.error || 'Auth failed');
      }
    } catch {
      Alert.alert('Error', 'Connection failed');
    }
  }

  async function sendMessage() {
    if (!input.trim()) return;
    const text = input.trim();
    setInput('');
    addMessage(text, 'user');
    setIsLoading(true);

    try {
      const res = await fetch(`${SERVER_URL}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ message: text, sessionId }),
      });
      const data = await res.json();
      setIsLoading(false);

      if (data.error) {
        addMessage('Error: ' + data.error, 'assistant');
      } else {
        if (data.sessionId) setSessionId(data.sessionId);
        addMessage(data.reply, 'assistant');
        speak(data.reply);
      }
    } catch {
      setIsLoading(false);
      addMessage('Connection error. Is the server running?', 'assistant');
    }
  }

  function addMessage(text: string, role: 'user' | 'assistant') {
    const msg: Message = { id: Date.now().toString(), text, role, timestamp: new Date() };
    setMessages(prev => [...prev, msg]);
    setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 100);
  }

  function speak(text: string) {
    Speech.stop();
    setIsSpeaking(true);
    Speech.speak(text, {
      language: 'en-US',
      pitch: 1.1,
      rate: 0.95,
      onDone: () => setIsSpeaking(false),
      onError: () => setIsSpeaking(false),
    });
  }

  function stopSpeaking() {
    Speech.stop();
    setIsSpeaking(false);
  }

  // --- Render ---

  if (!isLoggedIn) {
    return (
      <View style={styles.container}>
        <StatusBar barStyle="light-content" />
        <View style={styles.authScreen}>
          <Animated.View style={[styles.orb, { transform: [{ scale: pulseAnim }] }]}>
            <Ionicons name="lock-closed" size={40} color="#00d4ff" />
          </Animated.View>
          <Text style={styles.title}>JARVIS</Text>
          <Text style={styles.subtitle}>
            {authMode === 'setup' ? 'Set a password to secure your AI' : 'Enter password to unlock'}
          </Text>
          <View style={styles.authInputRow}>
            <TextInput
              style={styles.authInput}
              placeholder={authMode === 'setup' ? 'Create password (min 6 chars)' : 'Password'}
              placeholderTextColor="rgba(255,255,255,0.3)"
              secureTextEntry
              value={input}
              onChangeText={setInput}
              onSubmitEditing={handleAuth}
            />
            <TouchableOpacity style={styles.authBtn} onPress={handleAuth}>
              <Ionicons name="arrow-forward" size={20} color="#000" />
            </TouchableOpacity>
          </View>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" />

      {/* Header with orb */}
      <View style={styles.header}>
        <TouchableOpacity onPress={isSpeaking ? stopSpeaking : undefined}>
          <Animated.View style={[styles.orbSmall, isSpeaking && { transform: [{ scale: pulseAnim }] }]}>
            <Ionicons name={isSpeaking ? "volume-high" : "mic"} size={20} color="#00d4ff" />
          </Animated.View>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>JARVIS</Text>
        {isSpeaking && (
          <TouchableOpacity onPress={stopSpeaking} style={styles.stopBtn}>
            <Ionicons name="stop" size={16} color="#ff4444" />
          </TouchableOpacity>
        )}
      </View>

      {/* Messages */}
      <ScrollView ref={scrollRef} style={styles.messages} contentContainerStyle={styles.messagesContent}>
        {messages.map(msg => (
          <View key={msg.id} style={[styles.msgBubble, msg.role === 'user' ? styles.userBubble : styles.aiBubble]}>
            <Text style={[styles.msgText, msg.role === 'user' ? styles.userText : styles.aiText]}>{msg.text}</Text>
          </View>
        ))}
        {isLoading && (
          <View style={styles.aiBubble}>
            <Text style={styles.typingText}>Thinking...</Text>
          </View>
        )}
      </ScrollView>

      {/* Input */}
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.inputBar}>
          <TextInput
            style={styles.input}
            placeholder="Ask anything..."
            placeholderTextColor="rgba(255,255,255,0.3)"
            value={input}
            onChangeText={setInput}
            onSubmitEditing={sendMessage}
            returnKeyType="send"
          />
          <TouchableOpacity style={styles.sendBtn} onPress={sendMessage}>
            <Ionicons name="send" size={18} color="#00d4ff" />
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0f0c29' },
  // Auth screen
  authScreen: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 30 },
  orb: { width: 100, height: 100, borderRadius: 50, backgroundColor: 'rgba(0,212,255,0.15)', borderWidth: 1, borderColor: 'rgba(0,212,255,0.3)', justifyContent: 'center', alignItems: 'center', marginBottom: 24 },
  title: { fontSize: 36, fontWeight: '700', color: '#00d4ff', letterSpacing: 4, marginBottom: 8 },
  subtitle: { fontSize: 14, color: 'rgba(255,255,255,0.5)', marginBottom: 30 },
  authInputRow: { flexDirection: 'row', gap: 10, width: '100%', maxWidth: 320 },
  authInput: { flex: 1, backgroundColor: 'rgba(255,255,255,0.05)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)', borderRadius: 12, padding: 14, color: '#fff', fontSize: 16 },
  authBtn: { width: 48, height: 48, borderRadius: 24, backgroundColor: '#00d4ff', justifyContent: 'center', alignItems: 'center' },
  // Header
  header: { flexDirection: 'row', alignItems: 'center', paddingTop: 50, paddingHorizontal: 20, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.06)', gap: 12 },
  orbSmall: { width: 36, height: 36, borderRadius: 18, backgroundColor: 'rgba(0,212,255,0.15)', borderWidth: 1, borderColor: 'rgba(0,212,255,0.3)', justifyContent: 'center', alignItems: 'center' },
  headerTitle: { fontSize: 18, fontWeight: '600', color: '#fff', letterSpacing: 2, flex: 1 },
  stopBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: 'rgba(255,70,70,0.2)', borderWidth: 1, borderColor: 'rgba(255,70,70,0.3)', justifyContent: 'center', alignItems: 'center' },
  // Messages
  messages: { flex: 1 },
  messagesContent: { padding: 16, paddingBottom: 8 },
  msgBubble: { maxWidth: '85%', marginVertical: 4, padding: 12, borderRadius: 16 },
  userBubble: { alignSelf: 'flex-end', backgroundColor: 'rgba(0,212,255,0.15)', borderWidth: 1, borderColor: 'rgba(0,212,255,0.2)', borderBottomRightRadius: 4 },
  aiBubble: { alignSelf: 'flex-start', backgroundColor: 'rgba(255,255,255,0.05)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)', borderBottomLeftRadius: 4 },
  msgText: { fontSize: 15, lineHeight: 22 },
  userText: { color: '#c0efff' },
  aiText: { color: '#e0e0e0' },
  typingText: { color: '#00d4ff', fontStyle: 'italic', fontSize: 14 },
  // Input
  inputBar: { flexDirection: 'row', padding: 12, paddingBottom: Platform.OS === 'ios' ? 28 : 12, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.06)', gap: 8, alignItems: 'center' },
  input: { flex: 1, backgroundColor: 'rgba(255,255,255,0.04)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)', borderRadius: 20, paddingHorizontal: 16, paddingVertical: 10, color: '#fff', fontSize: 15 },
  sendBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: 'rgba(0,212,255,0.2)', borderWidth: 1, borderColor: 'rgba(0,212,255,0.3)', justifyContent: 'center', alignItems: 'center' },
});
