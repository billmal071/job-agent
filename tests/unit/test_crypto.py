"""Tests for encryption utilities."""

from job_agent.utils.crypto import encrypt, decrypt


def test_encrypt_decrypt():
    plaintext = "my_secret_password"
    ciphertext = encrypt(plaintext)
    assert ciphertext != plaintext
    assert decrypt(ciphertext) == plaintext


def test_different_encryptions():
    text = "same_text"
    c1 = encrypt(text)
    c2 = encrypt(text)
    # Fernet uses timestamp + IV, so same plaintext produces different ciphertext
    assert c1 != c2
    assert decrypt(c1) == text
    assert decrypt(c2) == text
