"""
비밀번호 해싱 유틸리티
"""
import hashlib
import secrets
import logging

logger = logging.getLogger(__name__)

# ========== 옵션 1: AES 암호화 (복호화 가능) - 주석 처리 ==========
# from cryptography.fernet import Fernet
# import base64
# import os
# 
# # 환경 변수에서 암호화 키 가져오기 (또는 고정 키)
# ENCRYPTION_KEY = os.getenv("PASSWORD_ENCRYPTION_KEY", "your-secret-key-32-chars-long!!")  # 32자리 키 필요
# 
# def encrypt_password(password: str) -> str:
#     """
#     비밀번호를 AES로 암호화 (복호화 가능)
#     """
#     # Fernet은 32바이트 키를 base64로 인코딩된 키를 요구
#     key = base64.urlsafe_b64encode(ENCRYPTION_KEY.encode()[:32].ljust(32, b'0'))
#     f = Fernet(key)
#     encrypted = f.encrypt(password.encode())
#     return encrypted.decode()
# 
# def decrypt_password(encrypted_password: str) -> str:
#     """
#     암호화된 비밀번호를 복호화
#     """
#     key = base64.urlsafe_b64encode(ENCRYPTION_KEY.encode()[:32].ljust(32, b'0'))
#     f = Fernet(key)
#     decrypted = f.decrypt(encrypted_password.encode())
#     return decrypted.decode()
# =================================================================

# ========== 옵션 2: 평문 저장 (보안 위험) ==========
def hash_password(password: str) -> str:
    """
    비밀번호를 평문으로 반환 (해시화 없음)
    """
    return password


def verify_password(password: str, password_hash: str) -> bool:
    """
    비밀번호 검증 (평문 비교)
    """
    if not password or not password_hash:
        logger.warning(f"[비밀번호 검증 실패] 빈 값 - password={'*' if password else None}, password_hash={'*' if password_hash else None}")
        return False
    
    result = password == password_hash
    if not result:
        logger.debug(f"[비밀번호 검증 실패] 불일치 - password_length={len(password)}, hash_length={len(password_hash)}")
    return result

# ========== 기존 해시화 함수 (주석 처리) ==========
# def hash_password(password: str) -> str:
#     """
#     비밀번호를 SHA-256으로 해싱
#     salt를 추가하여 보안 강화
#     """
#     # 랜덤 salt 생성
#     salt = secrets.token_hex(16)
#     # 비밀번호 + salt를 해싱
#     password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
#     # salt와 해시를 함께 저장 (형식: salt:hash)
#     return f"{salt}:{password_hash}"
# 
# 
# def verify_password(password: str, password_hash: str) -> bool:
#     """
#     비밀번호 검증
#     """
#     try:
#         # 저장된 해시에서 salt와 hash 분리
#         salt, stored_hash = password_hash.split(":")
#         # 입력된 비밀번호 + salt를 해싱
#         input_hash = hashlib.sha256((password + salt).encode()).hexdigest()
#         # 해시 비교
#         return input_hash == stored_hash
#     except (ValueError, AttributeError):
#         return False

