"""
키워드 수집 관련 모듈
키워드 분리, 조합 생성, 필터링 등의 기능 제공
의존성 없이 순수 Python 함수로 구현
"""
from typing import List, Optional
from itertools import combinations
import re
import logging

logger = logging.getLogger(__name__)


def split_keywords_by_space(keyword: str) -> List[str]:
    """
    키워드를 띄어쓰기로 나누어 단어 리스트 반환
    
    Args:
        keyword: 띄어쓰기로 구분된 키워드 문자열
    
    Returns:
        list: 단어 리스트 (빈 문자열 제거)
    
    Examples:
        >>> split_keywords_by_space("브라더 TN-269XL 재생토너")
        ['브라더', 'TN-269XL', '재생토너']
        
        >>> split_keywords_by_space("  단어1   단어2  단어3  ")
        ['단어1', '단어2', '단어3']
    """
    if not keyword:
        return []
    
    # 연속된 공백으로 분리하고 빈 문자열 제거
    words = re.split(r'\s+', keyword.strip())
    words = [w for w in words if w]
    
    return words


def generate_keyword_combinations(
    words: List[str], 
    min_length: int = 2, 
    max_length: Optional[int] = None
) -> List[str]:
    """
    단어 리스트에서 순차 조합 생성 (2단어 -> 3단어 -> ... -> max_length 단어)
    
    Args:
        words: 단어 리스트
        min_length: 최소 조합 길이 (기본값: 2)
        max_length: 최대 조합 길이 (None이면 words 길이)
    
    Returns:
        list: 조합된 키워드 문자열 리스트 (길이 순서대로 정렬)
    
    Examples:
        >>> words = ['브라더', 'TN-269XL', '재생토너']
        >>> generate_keyword_combinations(words, min_length=2, max_length=3)
        ['브라더 TN-269XL', '브라더 재생토너', 'TN-269XL 재생토너', 
         '브라더 TN-269XL 재생토너']
    """
    if not words:
        return []
    
    if max_length is None:
        max_length = len(words)
    
    # max_length는 words 길이를 초과할 수 없음
    max_length = min(max_length, len(words))
    
    if min_length > max_length:
        return []
    
    combinations_list = []
    
    # min_length 단어 조합부터 max_length 단어 조합까지
    for length in range(min_length, max_length + 1):
        # 길이에 맞는 모든 조합 생성
        for combo in combinations(range(len(words)), length):
            # 조합된 인덱스로 단어 조합
            combo_words = [words[i] for i in combo]
            combo_keyword = ' '.join(combo_words)
            combinations_list.append(combo_keyword)
    
    return combinations_list


def filter_keywords_by_length(
    keywords: List[str], 
    max_length: int = 10
) -> List[str]:
    """
    키워드 리스트에서 최대 길이 이하인 것만 필터링 (공백 제거 후 길이 계산)
    
    Args:
        keywords: 키워드 리스트
        max_length: 최대 길이 (기본값: 10, 공백 제거 후 길이)
    
    Returns:
        list: 필터링된 키워드 리스트
    
    Examples:
        >>> keywords = ['브라더 TN-269XL', '재생토너', '브라더 재생토너 HL-L3220CW']
        >>> filter_keywords_by_length(keywords, max_length=10)
        ['재생토너']
    """
    filtered = []
    for keyword in keywords:
        # 공백 제거 후 길이 계산
        keyword_no_space = keyword.replace(' ', '')
        if len(keyword_no_space) <= max_length:
            filtered.append(keyword)
    
    return filtered


def generate_keywords_from_product_name(
    product_name: str,
    min_length: int = 2,
    max_length: Optional[int] = None,
    max_keywords: Optional[int] = None,
    filter_by_length: Optional[int] = None
) -> List[str]:
    """
    상품명에서 키워드 조합 생성 (통합 함수)
    
    Args:
        product_name: 상품명 문자열
        min_length: 최소 조합 길이 (기본값: 2)
        max_length: 최대 조합 길이 (None이면 모든 단어)
        max_keywords: 최대 키워드 개수 (None이면 제한 없음)
        filter_by_length: 길이 필터링 (None이면 필터링 안 함, 공백 제거 후 길이)
    
    Returns:
        list: 생성된 키워드 조합 리스트
    
    Examples:
        >>> generate_keywords_from_product_name("브라더 TN-269XL 재생토너", min_length=2, max_keywords=10)
        ['브라더 TN-269XL', '브라더 재생토너', 'TN-269XL 재생토너', ...]
    """
    # 1. 키워드 분리
    words = split_keywords_by_space(product_name)
    
    if len(words) < min_length:
        return []
    
    # 2. 키워드 조합 생성
    keyword_combinations = generate_keyword_combinations(words, min_length, max_length)
    
    # 3. 길이 필터링 (옵션)
    if filter_by_length is not None:
        keyword_combinations = filter_keywords_by_length(keyword_combinations, filter_by_length)
    
    # 4. 개수 제한 (옵션)
    if max_keywords is not None and len(keyword_combinations) > max_keywords:
        keyword_combinations = keyword_combinations[:max_keywords]
    
    return keyword_combinations


def remove_duplicate_keywords(keywords: List[str]) -> List[str]:
    """
    키워드 리스트에서 중복 제거 (순서 유지)
    
    Args:
        keywords: 키워드 리스트
    
    Returns:
        list: 중복이 제거된 키워드 리스트 (순서 유지)
    
    Examples:
        >>> remove_duplicate_keywords(['키워드1', '키워드2', '키워드1', '키워드3'])
        ['키워드1', '키워드2', '키워드3']
    """
    seen = set()
    result = []
    
    for keyword in keywords:
        if keyword not in seen:
            seen.add(keyword)
            result.append(keyword)
    
    return result


def sort_keywords_by_length(keywords: List[str], reverse: bool = False) -> List[str]:
    """
    키워드를 길이 순으로 정렬
    
    Args:
        keywords: 키워드 리스트
        reverse: True이면 긴 것부터, False이면 짧은 것부터 (기본값: False)
    
    Returns:
        list: 길이 순으로 정렬된 키워드 리스트
    
    Examples:
        >>> sort_keywords_by_length(['긴 키워드 예시', '짧음', '중간 길이'])
        ['짧음', '중간 길이', '긴 키워드 예시']
    """
    return sorted(keywords, key=lambda x: len(x), reverse=reverse)


def filter_keywords_by_word_count(
    keywords: List[str],
    min_words: int = 1,
    max_words: Optional[int] = None
) -> List[str]:
    """
    키워드를 단어 개수로 필터링
    
    Args:
        keywords: 키워드 리스트
        min_words: 최소 단어 개수 (기본값: 1)
        max_words: 최대 단어 개수 (None이면 제한 없음)
    
    Returns:
        list: 필터링된 키워드 리스트
    
    Examples:
        >>> keywords = ['단어1', '단어1 단어2', '단어1 단어2 단어3']
        >>> filter_keywords_by_word_count(keywords, min_words=2, max_words=2)
        ['단어1 단어2']
    """
    filtered = []
    
    for keyword in keywords:
        word_count = len(split_keywords_by_space(keyword))
        
        if word_count < min_words:
            continue
        
        if max_words is not None and word_count > max_words:
            continue
        
        filtered.append(keyword)
    
    return filtered


def combine_keywords_with_global_keywords(
    base_keywords: List[str],
    global_keywords: List[str]
) -> List[str]:
    """
    기본 키워드와 글로벌 키워드를 조합
    
    Args:
        base_keywords: 기본 키워드 리스트
        global_keywords: 글로벌 키워드 리스트 (예: '추천', '비교', '순위' 등)
    
    Returns:
        list: 조합된 키워드 리스트
    
    Examples:
        >>> base = ['브라더', '재생토너']
        >>> global_kw = ['추천', '비교']
        >>> combine_keywords_with_global_keywords(base, global_kw)
        ['브라더 추천', '브라더 비교', '재생토너 추천', '재생토너 비교', 
         '브라더 재생토너 추천', '브라더 재생토너 비교']
    """
    if not base_keywords or not global_keywords:
        return []
    
    combined = []
    
    # 각 기본 키워드에 글로벌 키워드 추가
    for base_keyword in base_keywords:
        for global_keyword in global_keywords:
            combined.append(f"{base_keyword} {global_keyword}")
    
    # 기본 키워드 조합에 글로벌 키워드 추가
    if len(base_keywords) > 1:
        base_combined = ' '.join(base_keywords)
        for global_keyword in global_keywords:
            combined.append(f"{base_combined} {global_keyword}")
    
    return combined


def get_keyword_statistics(keywords: List[str]) -> dict:
    """
    키워드 리스트의 통계 정보 반환
    
    Args:
        keywords: 키워드 리스트
    
    Returns:
        dict: 통계 정보
            - total_count: 전체 개수
            - avg_length: 평균 길이
            - min_length: 최소 길이
            - max_length: 최대 길이
            - word_count_distribution: 단어 개수별 분포
    """
    if not keywords:
        return {
            'total_count': 0,
            'avg_length': 0,
            'min_length': 0,
            'max_length': 0,
            'word_count_distribution': {}
        }
    
    lengths = [len(kw) for kw in keywords]
    word_counts = [len(split_keywords_by_space(kw)) for kw in keywords]
    
    word_count_dist = {}
    for count in word_counts:
        word_count_dist[count] = word_count_dist.get(count, 0) + 1
    
    return {
        'total_count': len(keywords),
        'avg_length': sum(lengths) / len(lengths) if lengths else 0,
        'min_length': min(lengths) if lengths else 0,
        'max_length': max(lengths) if lengths else 0,
        'word_count_distribution': word_count_dist
    }
