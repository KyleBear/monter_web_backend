import { API_BASE_URL } from '../config.js';

// 공통 헤더 생성 함수
const getAuthHeaders = () => {
    const headers = {
        'Content-Type': 'application/json',
    };
    
    // 세션 토큰 가져오기
    const token = sessionStorage.getItem('sessionToken');
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    
    return headers;
};

// 짧은 랜덤 링크 생성 함수
const generateShortLink = () => {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let result = '';
    for (let i = 0; i < 10; i++) {
        result += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return result;
};

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

export const initRewardMgmtLinkPage = (container) => {
    // 관리자 권한 체크
    const userRole = sessionStorage.getItem('userRole');
    if (userRole !== 'admin') {
        container.innerHTML = `
            <div style="text-align: center; padding: 40px;">
                <h3>접근 권한이 없습니다.</h3>
                <p>이 페이지는 관리자만 접근할 수 있습니다.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = `
        <div class="reward-mgmt-link-info">
            <strong>리워드 링크 관리</strong><br>
            상품명, 쿼리, acq를 입력하여 짧은 랜덤 링크를 생성하고 관리할 수 있습니다.
        </div>

        <!-- 랜덤 링크 생성 섹션 -->
        <div class="reward-mgmt-link-form" style="margin-top: 20px; padding: 20px; background: #f9f9f9; border-radius: 8px;">
            <h3 style="margin-bottom: 15px;">랜덤 링크 생성</h3>
            <div class="form-group">
                <label>상품명 <span style="color: red;">*</span></label>
                <input type="text" id="link-product-name" placeholder="상품명을 입력하세요" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px;">
            </div>
            <div class="form-group" style="margin-top: 15px;">
                <label>쿼리 (Query) <span style="color: red;">*</span></label>
                <input type="text" id="link-query-input" placeholder="쿼리 키워드를 입력하세요" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px;">
            </div>
            <div class="form-group" style="margin-top: 15px;">
                <label>Acq <span style="color: red;">*</span></label>
                <input type="text" id="link-acq-input" placeholder="acq 키워드를 입력하세요" style="width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px;">
            </div>
            <div class="form-group" style="margin-top: 15px;">
                <button id="link-create-btn" class="btn-register" style="width: 100%; padding: 12px; font-size: 16px; font-weight: bold;">
                    랜덤 링크 생성
                </button>
            </div>
            <div style="margin-top: 20px; padding: 15px; background: #f0f8ff; border-left: 4px solid #007bff; border-radius: 4px;">
                <strong style="display: block; margin-bottom: 10px;">링크 생성 안내</strong>
                <p style="margin: 5px 0; font-size: 13px; color: #333;">생성된 링크로 접속하면 랜덤으로 선택된 키워드 조합으로 네이버 검색 페이지로 리다이렉트됩니다:</p>
                <pre style="margin: 10px 0; padding: 10px; background: #fff; border: 1px solid #ddd; border-radius: 4px; font-size: 12px; overflow-x: auto;">https://m.search.naver.com/search.naver?
  sm=mtp_sug.top&
  where=m&
  query={랜덤 선택된 query}&
  ackey={영문숫자 8글자 랜덤}&
  acq={랜덤 선택된 acq}&
  acr={0~10 랜덤}&
  qdt=0</pre>
            </div>
        </div>

        <!-- 생성된 링크 목록 -->
        <div id="link-list-container" style="margin-top: 30px;">
            <h3 style="margin-bottom: 15px;">생성된 링크 목록</h3>
            <div id="link-list-content">
                <table style="width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #ddd;">
                    <thead>
                        <tr style="background: #f8f9fa; border-bottom: 2px solid #ddd;">
                            <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">상품명</th>
                            <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">짧은 링크</th>
                            <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">쿼리</th>
                            <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">Acq</th>
                            <th style="padding: 12px; text-align: left; border: 1px solid #ddd;">키워드 개수</th>
                            <th style="padding: 12px; text-align: center; border: 1px solid #ddd;">작업</th>
                        </tr>
                    </thead>
                    <tbody id="link-list-tbody">
                        <tr>
                            <td colspan="6" style="padding: 20px; text-align: center; color: #666;">로딩 중...</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    `;

    initRewardMgmtLinkEvents();
    loadLinkList();
};


// 이벤트 초기화
const initRewardMgmtLinkEvents = () => {
    // 랜덤 링크 생성 버튼
    const createBtn = document.getElementById('link-create-btn');
    if (createBtn) {
        createBtn.addEventListener('click', async () => {
            const productName = document.getElementById('link-product-name').value.trim();
            const query = document.getElementById('link-query-input').value.trim();
            const acq = document.getElementById('link-acq-input').value.trim();
            
            if (!productName) {
                alert('상품명을 입력해주세요.');
                return;
            }

            if (!query) {
                alert('쿼리를 입력해주세요.');
                return;
            }

            if (!acq) {
                alert('acq를 입력해주세요.');
                return;
            }

            await createNewLink(productName, query, acq);
        });
    }
};

// 새 링크 생성
const createNewLink = async (productName, query, acq) => {
    try {
        const baseUrl = window.location.origin;

        // 백엔드 API 호출 (예상 엔드포인트: POST /rewards/links)
        // short_link는 백엔드에서 자동 생성
        const url = `${API_BASE_URL}/rewards/links`;
        const requestBody = {
            product_name: productName,
            keywords: [{
                query: query,
                acq: acq
            }]
        };

        console.log('링크 생성 API 호출:', url, requestBody);

        const response = await fetch(url, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify(requestBody)
        });

        if (response.ok) {
            const data = await response.json();
            console.log('링크 생성 성공:', data);
            
            // 백엔드에서 반환된 short_code 사용
            const shortCode = data.data?.short_code || data.short_code;
            if (!shortCode) {
                alert('링크 생성은 성공했지만 short_code를 받지 못했습니다.');
                loadLinkList();
                return;
            }
            const fullLink = `${baseUrl}/redirect/${shortCode}`;
            
            alert(`링크가 생성되었습니다.\n${fullLink}`);
            
            // 입력 필드 초기화
            document.getElementById('link-product-name').value = '';
            document.getElementById('link-query-input').value = '';
            document.getElementById('link-acq-input').value = '';
            
            // 목록 새로고침
            loadLinkList();
        } else {
            let errorMessage = `서버 오류 (${response.status})`;
            try {
                const errorText = await response.text();
                if (errorText) {
                    try {
                        const errorData = JSON.parse(errorText);
                        // 오류 메시지 추출 (다양한 형식 지원)
                        if (typeof errorData === 'string') {
                            errorMessage = errorData;
                        } else if (errorData.message && typeof errorData.message === 'string') {
                            errorMessage = errorData.message;
                        } else if (errorData.detail && typeof errorData.detail === 'string') {
                            errorMessage = errorData.detail;
                        } else if (errorData.error && typeof errorData.error === 'string') {
                            errorMessage = errorData.error;
                        } else if (typeof errorData === 'object') {
                            errorMessage = JSON.stringify(errorData);
                        } else {
                            errorMessage = errorText;
                        }
                    } catch (e) {
                        errorMessage = errorText;
                    }
                }
            } catch (e) {
                console.error('오류 메시지 파싱 실패:', e);
            }
            
            console.error('링크 생성 실패:', response.status, errorMessage);
            alert(`링크 생성 실패: ${errorMessage}`);
        }
    } catch (error) {
        console.error('링크 생성 API 호출 오류:', error);
        alert('서버 연결에 실패했습니다. 네트워크를 확인해주세요.');
    }
};


// 링크 목록 로드
const loadLinkList = async () => {
    try {
        // 백엔드 API 호출 (예상 엔드포인트: GET /rewards/links)
        const url = `${API_BASE_URL}/rewards/links`;
        
        console.log('링크 목록 API 호출:', url);

        const response = await fetch(url, {
            method: 'GET',
            headers: getAuthHeaders()
        });

        if (response.ok) {
            const data = await response.json();
            console.log('링크 목록 API 응답:', data);
            
            let links = [];
            if (data.data && data.data.links && Array.isArray(data.data.links)) {
                links = data.data.links;
            } else if (data.links && Array.isArray(data.links)) {
                links = data.links;
            } else if (Array.isArray(data)) {
                links = data;
            }
            
            renderLinkList(links);
        } else {
            let errorMessage = `서버 오류 (${response.status})`;
            try {
                const errorText = await response.text();
                if (errorText) {
                    try {
                        const errorData = JSON.parse(errorText);
                        if (typeof errorData === 'string') {
                            errorMessage = errorData;
                        } else if (errorData.message && typeof errorData.message === 'string') {
                            errorMessage = errorData.message;
                        } else if (errorData.detail && typeof errorData.detail === 'string') {
                            errorMessage = errorData.detail;
                        } else if (errorData.error && typeof errorData.error === 'string') {
                            errorMessage = errorData.error;
                        } else {
                            errorMessage = errorText;
                        }
                    } catch (e) {
                        errorMessage = errorText;
                    }
                }
            } catch (e) {
                console.error('오류 메시지 파싱 실패:', e);
            }
            
            console.error('링크 목록 로드 실패:', response.status, errorMessage);
            const container = document.getElementById('link-list-content');
            if (container) {
                container.innerHTML = `<p style="text-align: center; padding: 20px; color: #dc3545;">링크 목록을 불러올 수 없습니다.<br>오류: ${errorMessage}</p>`;
            }
        }
    } catch (error) {
        console.error('API 호출 오류:', error);
        const container = document.getElementById('link-list-content');
        if (container) {
            container.innerHTML = '<p style="text-align: center; padding: 20px; color: #dc3545;">서버 연결에 실패했습니다. 네트워크를 확인해주세요.</p>';
        }
    }
};

// 링크 목록 렌더링
const renderLinkList = (links) => {
    const tbody = document.getElementById('link-list-tbody');
    
    if (!tbody) {
        console.error('link-list-tbody를 찾을 수 없습니다.');
        return;
    }

    if (!links || links.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="padding: 40px; text-align: center; color: #666;">생성된 링크가 없습니다.</td></tr>';
        return;
    }

    const baseUrl = window.location.origin;
    
    tbody.innerHTML = links.map((link, index) => {
        const linkId = link.link_id || link.id || index;
        const shortCode = link.short_code || link.short_link || link.shortLink || '';
        const productName = link.product_name || link.productName || '상품명 없음';
        const keywords = link.keywords || link.keyword_combinations || [];
        const fullLink = `${baseUrl}/redirect/${shortCode}`;
        
        // 첫 번째 키워드 조합의 query와 acq 표시 (대표값)
        const firstKeyword = keywords.length > 0 ? keywords[0] : null;
        const displayQuery = firstKeyword ? (firstKeyword.query_keyword || firstKeyword.query || '-') : '-';
        const displayAcq = firstKeyword ? (firstKeyword.acq_keyword || firstKeyword.acq || '-') : '-';
        
        return `
            <tr class="link-item" data-link-id="${linkId}" style="border-bottom: 1px solid #ddd;">
                <td style="padding: 12px; border: 1px solid #ddd;">${productName}</td>
                <td style="padding: 12px; border: 1px solid #ddd;">
                    <div style="display: flex; align-items: center; gap: 5px;">
                        <input type="text" id="link-url-${linkId}" value="${fullLink}" readonly style="flex: 1; padding: 6px; border: 1px solid #ddd; border-radius: 4px; background: #f5f5f5; font-size: 12px;">
                        <button class="btn-copy-link" data-link-id="${linkId}" style="padding: 6px 12px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px;">복사</button>
                    </div>
                </td>
                <td style="padding: 12px; border: 1px solid #ddd;">${displayQuery}</td>
                <td style="padding: 12px; border: 1px solid #ddd;">${displayAcq}</td>
                <td style="padding: 12px; border: 1px solid #ddd; text-align: center;">${keywords.length}개</td>
                <td style="padding: 12px; border: 1px solid #ddd; text-align: center;">
                    <div style="display: flex; gap: 5px; justify-content: center;">
                        <button class="btn-view-keywords" data-link-id="${linkId}" style="padding: 6px 12px; background: #17a2b8; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px;">키워드</button>
                        <button class="btn-delete-link" data-link-id="${linkId}" style="padding: 6px 12px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px;">삭제</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    // 이벤트 바인딩
    bindLinkEvents(links);
};

// 링크 관련 이벤트 바인딩
const bindLinkEvents = (links) => {
    // 링크 복사 버튼
    document.querySelectorAll('.btn-copy-link').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const linkId = btn.getAttribute('data-link-id');
            const input = document.getElementById(`link-url-${linkId}`);
            if (input) {
                input.select();
                document.execCommand('copy');
                alert('링크가 클립보드에 복사되었습니다.');
            }
        });
    });

    // 링크 삭제 버튼
    document.querySelectorAll('.btn-delete-link').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const linkId = btn.getAttribute('data-link-id');
            if (confirm('이 링크를 삭제하시겠습니까?')) {
                await deleteLink(linkId);
            }
        });
    });

    // 키워드 보기 버튼
    document.querySelectorAll('.btn-view-keywords').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const linkId = btn.getAttribute('data-link-id');
            const link = links.find(l => (l.id || l.link_id) == linkId);
            if (link) {
                showKeywordModal(link);
            }
        });
    });
};

// 키워드 모달 표시
const showKeywordModal = (link) => {
    const keywords = link.keywords || link.keyword_combinations || [];
    const linkId = link.id || link.link_id;
    const productName = link.product_name || link.productName || '상품명 없음';
    
    const modal = document.createElement('div');
    modal.id = 'keyword-modal';
    modal.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; display: flex; justify-content: center; align-items: center;';
    
    modal.innerHTML = `
        <div style="background: white; padding: 30px; border-radius: 8px; max-width: 800px; width: 90%; max-height: 80vh; overflow-y: auto;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h3>${productName} - 키워드 조합 관리</h3>
                <button id="close-keyword-modal" style="padding: 5px 15px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer;">닫기</button>
            </div>
            
            <div style="margin-bottom: 15px;">
                <button class="btn-add-keyword" data-link-id="${linkId}" style="padding: 8px 15px; background: #28a745; color: white; border: none; border-radius: 4px; cursor: pointer;">+ 키워드 추가</button>
            </div>
            
            <div class="keyword-list" id="keyword-list-${linkId}">
                ${keywords.length > 0 ? keywords.map((keyword, kwIndex) => {
                    const kwId = keyword.keyword_id || keyword.id || kwIndex;
                    const query = keyword.query_keyword || keyword.query || '';
                    const acq = keyword.acq_keyword || keyword.acq || '';
                    return `
                        <div class="keyword-item" data-keyword-id="${kwId}" style="display: flex; gap: 10px; margin-bottom: 8px; padding: 10px; background: #f9f9f9; border-radius: 4px;">
                            <input type="text" class="keyword-query" value="${query}" placeholder="query 키워드" style="flex: 1; padding: 6px; border: 1px solid #ddd; border-radius: 4px;">
                            <input type="text" class="keyword-acq" value="${acq}" placeholder="acq 키워드" style="flex: 1; padding: 6px; border: 1px solid #ddd; border-radius: 4px;">
                            <button class="btn-save-keyword" data-link-id="${linkId}" data-keyword-id="${kwId}" style="padding: 6px 12px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px;">저장</button>
                            <button class="btn-delete-keyword" data-link-id="${linkId}" data-keyword-id="${kwId}" style="padding: 6px 12px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px;">삭제</button>
                        </div>
                    `;
                }).join('') : '<p style="color: #666; font-size: 14px;">등록된 키워드 조합이 없습니다.</p>'}
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // 닫기 버튼
    modal.querySelector('#close-keyword-modal').addEventListener('click', () => {
        document.body.removeChild(modal);
    });
    
    // 모달 외부 클릭 시 닫기
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            document.body.removeChild(modal);
        }
    });
    
    // 키워드 추가 버튼
    modal.querySelector('.btn-add-keyword').addEventListener('click', () => {
        addKeywordRow(linkId, modal);
    });
    
    // 키워드 저장/삭제 버튼 이벤트
    modal.querySelectorAll('.btn-save-keyword').forEach(btn => {
        btn.addEventListener('click', async () => {
            const keywordId = btn.getAttribute('data-keyword-id');
            const keywordItem = btn.closest('.keyword-item');
            const query = keywordItem.querySelector('.keyword-query').value.trim();
            const acq = keywordItem.querySelector('.keyword-acq').value.trim();
            
            if (!query || !acq) {
                alert('query와 acq 키워드를 모두 입력해주세요.');
                return;
            }

            await saveKeyword(linkId, keywordId, query, acq);
            document.body.removeChild(modal);
            loadLinkList();
        });
    });
    
    modal.querySelectorAll('.btn-delete-keyword').forEach(btn => {
        btn.addEventListener('click', async () => {
            const keywordId = btn.getAttribute('data-keyword-id');
            
            if (confirm('이 키워드 조합을 삭제하시겠습니까?')) {
                await deleteKeyword(linkId, keywordId);
                document.body.removeChild(modal);
                loadLinkList();
            }
        });
    });
};

// 키워드 행 추가
const addKeywordRow = (linkId, modal) => {
    const keywordList = document.getElementById(`keyword-list-${linkId}`);
    if (!keywordList) return;

    const newKeywordId = `new_${Date.now()}`;
    const keywordRow = document.createElement('div');
    keywordRow.className = 'keyword-item';
    keywordRow.setAttribute('data-keyword-id', newKeywordId);
    keywordRow.style.cssText = 'display: flex; gap: 10px; margin-bottom: 8px; padding: 10px; background: #f9f9f9; border-radius: 4px;';
    keywordRow.innerHTML = `
        <input type="text" class="keyword-query" value="" placeholder="query 키워드" style="flex: 1; padding: 6px; border: 1px solid #ddd; border-radius: 4px;">
        <input type="text" class="keyword-acq" value="" placeholder="acq 키워드" style="flex: 1; padding: 6px; border: 1px solid #ddd; border-radius: 4px;">
        <button class="btn-save-keyword" data-link-id="${linkId}" data-keyword-id="${newKeywordId}" style="padding: 6px 12px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px;">저장</button>
        <button class="btn-delete-keyword" data-link-id="${linkId}" data-keyword-id="${newKeywordId}" style="padding: 6px 12px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px;">삭제</button>
    `;

    keywordList.appendChild(keywordRow);

    // 새로 추가된 행의 이벤트 바인딩
    keywordRow.querySelector('.btn-save-keyword').addEventListener('click', async (e) => {
        const query = keywordRow.querySelector('.keyword-query').value.trim();
        const acq = keywordRow.querySelector('.keyword-acq').value.trim();
        
        if (!query || !acq) {
            alert('query와 acq 키워드를 모두 입력해주세요.');
            return;
        }

        await saveKeyword(linkId, newKeywordId, query, acq);
        if (modal) {
            document.body.removeChild(modal);
        }
        loadLinkList();
    });

    keywordRow.querySelector('.btn-delete-keyword').addEventListener('click', () => {
        keywordRow.remove();
    });
};

// 키워드 저장
const saveKeyword = async (linkId, keywordId, query, acq) => {
    try {
        // 새 키워드인 경우
        const isNew = keywordId.toString().startsWith('new_');
        const url = isNew 
            ? `${API_BASE_URL}/rewards/links/${linkId}/keywords`  // POST
            : `${API_BASE_URL}/rewards/links/${linkId}/keywords/${keywordId}`;  // PUT

        const method = isNew ? 'POST' : 'PUT';
        const requestBody = {
            query: query,
            acq: acq
        };

        console.log('키워드 저장 API 호출:', url, method, requestBody);

        const response = await fetch(url, {
            method: method,
            headers: getAuthHeaders(),
            body: JSON.stringify(requestBody)
        });

        if (response.ok) {
            const data = await response.json();
            console.log('키워드 저장 성공:', data);
            alert('키워드가 저장되었습니다.');
            loadLinkList(); // 목록 새로고침
        } else {
            let errorMessage = `서버 오류 (${response.status})`;
            try {
                const errorText = await response.text();
                if (errorText) {
                    try {
                        const errorData = JSON.parse(errorText);
                        if (typeof errorData === 'string') {
                            errorMessage = errorData;
                        } else if (errorData.message && typeof errorData.message === 'string') {
                            errorMessage = errorData.message;
                        } else if (errorData.detail && typeof errorData.detail === 'string') {
                            errorMessage = errorData.detail;
                        } else if (errorData.error && typeof errorData.error === 'string') {
                            errorMessage = errorData.error;
                        } else {
                            errorMessage = errorText;
                        }
                    } catch (e) {
                        errorMessage = errorText;
                    }
                }
            } catch (e) {
                console.error('오류 메시지 파싱 실패:', e);
            }
            
            console.error('키워드 저장 실패:', response.status, errorMessage);
            alert(`키워드 저장 실패: ${errorMessage}`);
        }
    } catch (error) {
        console.error('키워드 저장 API 호출 오류:', error);
        alert('서버 연결에 실패했습니다. 네트워크를 확인해주세요.');
    }
};

// 키워드 삭제
const deleteKeyword = async (linkId, keywordId) => {
    try {
        const url = `${API_BASE_URL}/rewards/links/${linkId}/keywords/${keywordId}`;
        
        console.log('키워드 삭제 API 호출:', url);

        const response = await fetch(url, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });

        if (response.ok) {
            console.log('키워드 삭제 성공');
            alert('키워드가 삭제되었습니다.');
            loadLinkList(); // 목록 새로고침
        } else {
            let errorMessage = `서버 오류 (${response.status})`;
            try {
                const errorText = await response.text();
                if (errorText) {
                    try {
                        const errorData = JSON.parse(errorText);
                        if (typeof errorData === 'string') {
                            errorMessage = errorData;
                        } else if (errorData.message && typeof errorData.message === 'string') {
                            errorMessage = errorData.message;
                        } else if (errorData.detail && typeof errorData.detail === 'string') {
                            errorMessage = errorData.detail;
                        } else if (errorData.error && typeof errorData.error === 'string') {
                            errorMessage = errorData.error;
                        } else {
                            errorMessage = errorText;
                        }
                    } catch (e) {
                        errorMessage = errorText;
                    }
                }
            } catch (e) {
                console.error('오류 메시지 파싱 실패:', e);
            }
            
            console.error('키워드 삭제 실패:', response.status, errorMessage);
            alert(`키워드 삭제 실패: ${errorMessage}`);
        }
    } catch (error) {
        console.error('키워드 삭제 API 호출 오류:', error);
        alert('서버 연결에 실패했습니다. 네트워크를 확인해주세요.');
    }
};

// 링크 삭제
const deleteLink = async (linkId) => {
    try {
        const url = `${API_BASE_URL}/rewards/links/${linkId}`;
        
        console.log('링크 삭제 API 호출:', url);

        const response = await fetch(url, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });

        if (response.ok) {
            console.log('링크 삭제 성공');
            alert('링크가 삭제되었습니다.');
            loadLinkList(); // 목록 새로고침
        } else {
            let errorMessage = `서버 오류 (${response.status})`;
            try {
                const errorText = await response.text();
                if (errorText) {
                    try {
                        const errorData = JSON.parse(errorText);
                        if (typeof errorData === 'string') {
                            errorMessage = errorData;
                        } else if (errorData.message && typeof errorData.message === 'string') {
                            errorMessage = errorData.message;
                        } else if (errorData.detail && typeof errorData.detail === 'string') {
                            errorMessage = errorData.detail;
                        } else if (errorData.error && typeof errorData.error === 'string') {
                            errorMessage = errorData.error;
                        } else {
                            errorMessage = errorText;
                        }
                    } catch (e) {
                        errorMessage = errorText;
                    }
                }
            } catch (e) {
                console.error('오류 메시지 파싱 실패:', e);
            }
            
            console.error('링크 삭제 실패:', response.status, errorMessage);
            alert(`링크 삭제 실패: ${errorMessage}`);
        }
    } catch (error) {
        console.error('링크 삭제 API 호출 오류:', error);
        alert('서버 연결에 실패했습니다. 네트워크를 확인해주세요.');
    }
};
