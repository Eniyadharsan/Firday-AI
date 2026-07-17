"""Comprehensive tests for FRIDAY modules."""

import pytest
from friday.modules import music, image, search, news, auth, memory, video, agents


class TestAuth:
    def test_hash_and_verify_correct(self):
        hashed = auth.hash_password("mypassword123")
        assert auth.verify_password("mypassword123", hashed) is True

    def test_hash_and_verify_wrong(self):
        hashed = auth.hash_password("mypassword123")
        assert auth.verify_password("wrongpassword", hashed) is False

    def test_hash_produces_different_salts(self):
        h1 = auth.hash_password("same")
        h2 = auth.hash_password("same")
        assert h1 != h2  # Different salts

    def test_make_token_returns_string(self):
        token = auth.make_token("user123", "test@test.com")
        assert isinstance(token, str)
        assert len(token) > 20

    def test_verify_token_valid(self):
        token = auth.make_token("user123", "test@test.com")
        payload = auth.verify_token(token)
        assert payload is not None
        assert payload["sub"] == "user123"
        assert payload["email"] == "test@test.com"

    def test_verify_token_invalid(self):
        assert auth.verify_token("invalid.token.here") is None
        assert auth.verify_token("") is None

    def test_signup_short_password(self):
        result = auth.signup("short@test.com", "123", "Short")
        assert "error" in result

    def test_signup_invalid_email(self):
        result = auth.signup("notanemail", "password123", "Test")
        assert "error" in result


class TestMusic:
    def test_is_music_request(self):
        assert music.is_music_request("play a song") is True
        assert music.is_music_request("play talking to the moon") is True

    def test_not_music_request(self):
        assert music.is_music_request("what time is it?") is False

    def test_youtube_url_format(self):
        url = music.get_youtube_url("Shape of You Ed Sheeran")
        assert "youtube.com" in url

    def test_extract_song(self):
        assert music.extract_song_from_reply("[PLAY_MUSIC:Hello - Adele]") == "Hello - Adele"

    def test_extract_song_none(self):
        assert music.extract_song_from_reply("no music here") is None


class TestImage:
    def test_is_image_request_generate(self):
        assert image.is_image_request("generate an image of a cat") is True

    def test_is_image_request_map(self):
        assert image.is_image_request("map of India") is True
        assert image.is_image_request("show me Chennai map") is True

    def test_is_image_request_give_me(self):
        assert image.is_image_request("give me a picture of sunset") is True

    def test_not_image_request(self):
        assert image.is_image_request("what is python?") is False

    def test_generate_url(self):
        url = image.generate_image_url("a red car on highway")
        assert "pollinations.ai" in url
        assert "1024" in url

    def test_map_prompt_enhanced(self):
        url = image.generate_image_url("map of Chennai")
        assert "cartographic" in url.lower() or "geographic" in url.lower()


class TestVideo:
    def test_is_video_request(self):
        assert video.is_video_request("create a video of sunset") is True
        assert video.is_video_request("generate a clip of waves") is True

    def test_not_video_request(self):
        assert video.is_video_request("what is AI?") is False


class TestAgents:
    def test_detect_coding_agent(self):
        assert agents.detect_agent("write a python function to sort a list") == "coding"

    def test_detect_travel_agent(self):
        assert agents.detect_agent("plan my vacation to Bali") == "travel"

    def test_detect_finance_agent(self):
        assert agents.detect_agent("help me budget my monthly expenses") == "finance"

    def test_detect_none_for_simple(self):
        assert agents.detect_agent("hi") is None

    def test_list_agents(self):
        agent_list = agents.list_agents()
        assert len(agent_list) >= 5
        assert all("name" in a for a in agent_list)


class TestMemory:
    def test_save_and_get(self):
        memory.save_message("test_user", "test_session", "user", "hello")
        history = memory.get_history("test_user", "test_session")
        assert any(m["content"] == "hello" for m in history)

    def test_get_all_sessions(self):
        memory.save_message("test_user2", "sess1", "user", "msg1")
        sessions = memory.get_all_sessions("test_user2")
        assert len(sessions) >= 1
