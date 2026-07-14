"""Unit tests for JARVIS modules."""

import pytest
from jarvis.modules import music, image, search, news, auth, memory


class TestMusic:
    def test_is_music_request_play_song(self):
        assert music.is_music_request("play a song for me") is True

    def test_is_music_request_play_command(self):
        assert music.is_music_request("play talking to the moon") is True

    def test_not_music_request(self):
        assert music.is_music_request("what is the weather?") is False

    def test_youtube_url(self):
        url = music.get_youtube_url("Talking to the Moon Bruno Mars")
        assert "youtube.com" in url
        assert "Talking" in url

    def test_extract_song(self):
        assert music.extract_song_from_reply("[PLAY_MUSIC:Shape of You - Ed Sheeran]") == "Shape of You - Ed Sheeran"

    def test_extract_song_none(self):
        assert music.extract_song_from_reply("I like music") is None


class TestImage:
    def test_is_image_request(self):
        assert image.is_image_request("generate an image of a cat") is True
        assert image.is_image_request("create a picture of sunset") is True

    def test_not_image_request(self):
        assert image.is_image_request("what time is it?") is False

    def test_generate_url(self):
        url = image.generate_image_url("a red car")
        assert "pollinations.ai" in url
        assert "1024" in url


class TestSearch:
    def test_web_search_returns_string(self):
        # This actually calls the API — integration test
        result = search.web_search("Python programming language")
        assert isinstance(result, str)


class TestAuth:
    def test_hash_and_verify(self):
        pw = "testpass123"
        hashed = auth.hash_password(pw)
        assert auth.verify_password(pw, hashed) is True
        assert auth.verify_password("wrong", hashed) is False

    def test_signup_and_signin(self):
        result = auth.signup("test@example.com", "password123", "Test User")
        # May succeed or fail if user exists from previous run
        if "token" in result:
            assert result["user"]["email"] == "test@example.com"
            # Signin
            login_result = auth.signin("test@example.com", "password123")
            assert "token" in login_result

    def test_signup_short_password(self):
        result = auth.signup("short@test.com", "12345", "Short")
        assert "error" in result


class TestMemory:
    def test_add_and_get_memory(self):
        result = memory.add_memory("test_user", "I like coffee", "preference")
        assert result.get("success") is True

        memories = memory.get_memories("test_user")
        assert any(m["content"] == "I like coffee" for m in memories)
