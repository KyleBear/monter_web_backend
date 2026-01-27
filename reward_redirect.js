import { API_BASE_URL } from '../config.js';

// 랜덤 문자열 생성 (영문숫자 8글자)
const generateRandomString = (length = 8) => {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let result = '';
    for (let i = 0; i < length; i++) {
        result += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return result;
};

// 랜덤 숫자 생성 (0~10)
const generateRandomNumber = (min = 0, max = 10) => {
    return Math.floor(Math.random() * (max - min + 1)) + min;
};

// URL에서 짧은 링크 추출
const getShortLinkFromUrl = () => {
    const path = window.location.pathname;
    // 예: /redirect/v8ZSBUT43vj
    const parts = path.split('/');
    if (parts.length >= 3 && parts[1] === 'redirect') {
        return parts[2];
    }
    return null;
};

// 리다이렉트 실행
const redirectToNaver = async () => {
    try {
        const shortLink = getShortLinkFromUrl();
        
        if (!shortLink) {
            console.error('짧은 링크를 찾을 수 없습니다.');
            document.body.innerHTML = '<div style="text-align: center; padding: 40px;"><h3>잘못된 링크입니다.</h3></div>';
            return;
        }

        console.log('짧은 링크:', shortLink);

        // 백엔드 API 호출하여 해당 링크의 키워드 조합 가져오기
        // 예상 엔드포인트: GET /rewards/links/{shortLink}
        const url = `${API_BASE_URL}/rewards/links/${shortLink}`;
        
        console.log('링크 정보 API 호출:', url);

        const response = await fetch(url, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (response.ok) {
            const data = await response.json();
            console.log('링크 정보 API 응답:', data);
            
            // 응답에서 키워드 조합 가져오기
            let linkData = null;
            if (data.data && data.data.link) {
                linkData = data.data.link;
            } else if (data.link) {
                linkData = data.link;
            } else {
                linkData = data;
            }

            const keywords = linkData?.keywords || linkData?.keyword_combinations || [];
            
            if (!keywords || keywords.length === 0) {
                console.error('키워드 조합이 없습니다.');
                document.body.innerHTML = '<div style="text-align: center; padding: 40px;"><h3>등록된 키워드가 없습니다.</h3></div>';
                return;
            }

            // 랜덤으로 키워드 조합 선택
            const randomKeyword = keywords[Math.floor(Math.random() * keywords.length)];
            const query = randomKeyword.query || randomKeyword.query_keyword || '';
            const acq = randomKeyword.acq || randomKeyword.acq_keyword || '';

            if (!query || !acq) {
                console.error('키워드 정보가 올바르지 않습니다.');
                document.body.innerHTML = '<div style="text-align: center; padding: 40px;"><h3>키워드 정보가 올바르지 않습니다.</h3></div>';
                return;
            }

            // 네이버 검색 URL 생성
            const ackey = generateRandomString(8);
            const acr = generateRandomNumber(0, 10);
            
            const naverUrl = `https://m.search.naver.com/search.naver?` +
                `sm=mtp_sug.top&` +
                `where=m&` +
                `query=${encodeURIComponent(query)}&` +
                `ackey=${ackey}&` +
                `acq=${encodeURIComponent(acq)}&` +
                `acr=${acr}&` +
                `qdt=0`;

            console.log('네이버 URL 생성:', naverUrl);

            // 리다이렉트
            window.location.href = naverUrl;

        } else {
            let errorData = {};
            try {
                const errorText = await response.text();
                errorData = errorText ? JSON.parse(errorText) : {};
            } catch (e) {
                errorData = { message: `서버 오류 (${response.status})` };
            }
            
            console.error('링크 정보 로드 실패:', response.status, errorData);
            document.body.innerHTML = `<div style="text-align: center; padding: 40px;"><h3>링크를 찾을 수 없습니다.</h3><p>${errorData.message || '서버 오류가 발생했습니다.'}</p></div>`;
        }
    } catch (error) {
        console.error('API 호출 오류:', error);
        document.body.innerHTML = '<div style="text-align: center; padding: 40px;"><h3>서버 연결에 실패했습니다.</h3><p>네트워크를 확인해주세요.</p></div>';
    }
};

// 페이지 로드 시 리다이렉트 실행
document.addEventListener('DOMContentLoaded', () => {
    redirectToNaver();
});
