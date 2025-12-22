"""
비밀번호 해싱 유틸리티
"""
import hashlib
import secrets


def hash_password(password: str) -> str:
    """
    비밀번호를 SHA-256으로 해싱
    salt를 추가하여 보안 강화
    """
    # 랜덤 salt 생성
    salt = secrets.token_hex(16)
    # 비밀번호 + salt를 해싱
    password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    # salt와 해시를 함께 저장 (형식: salt:hash)
    return f"{salt}:{password_hash}"


def verify_password(password: str, password_hash: str) -> bool:
    """
    비밀번호 검증
    """
    try:
        # 저장된 해시에서 salt와 hash 분리
        salt, stored_hash = password_hash.split(":")
        # 입력된 비밀번호 + salt를 해싱
        input_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        # 해시 비교
        return input_hash == stored_hash
    except (ValueError, AttributeError):
        return False

