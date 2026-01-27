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

// API 호출 헬퍼 함수
async function apiCall(url, options = {}) {
    try {
        const token = localStorage.getItem('token');
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        
        const response = await fetch(url, {
            ...options,
            headers
        });
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: '서버 오류가 발생했습니다.' }));
            throw new Error(errorData.detail || `HTTP ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error('API 호출 오류:', error);
        throw error;
    }
}

// 링크 목록 로드
async function loadLinks() {
    try {
        const data = await apiCall(`${API_BASE_URL}/rewards/links`);
        
        if (data.success && data.data.links) {
            displayLinks(data.data.links);
        } else {
            console.error('링크 목록 로드 실패:', data);
            showMessage('링크 목록을 불러오는데 실패했습니다.', 'error');
        }
    } catch (error) {
        console.error('링크 목록 로드 오류:', error);
        showMessage('링크 목록을 불러오는데 실패했습니다.', 'error');
    }
}

// 링크 목록 표시
function displayLinks(links) {
    const linksContainer = document.getElementById('linksContainer');
    if (!linksContainer) return;
    
    if (links.length === 0) {
        linksContainer.innerHTML = '<div class="empty-state">등록된 링크가 없습니다.</div>';
        return;
    }
    
    linksContainer.innerHTML = links.map(link => `
        <div class="link-card" data-link-id="${link.link_id}">
            <div class="link-header">
                <h3>${link.product_name || '상품명 없음'}</h3>
                <div class="link-actions">
                    <button class="btn-copy" onclick="copyLink('${link.short_code}')" title="링크 복사">
                        <span>📋</span> 복사
                    </button>
                    <button class="btn-edit" onclick="editLink(${link.link_id})" title="수정">
                        ✏️ 수정
                    </button>
                    <button class="btn-delete" onclick="deleteLink(${link.link_id})" title="삭제">
                        🗑️ 삭제
                    </button>
                </div>
            </div>
            <div class="link-info">
                <div class="short-code">
                    <strong>짧은 링크:</strong> 
                    <code>${window.location.origin}/redirect/${link.short_code}</code>
                </div>
                <div class="keyword-count">
                    <strong>키워드 개수:</strong> ${link.keyword_count}개
                </div>
            </div>
            <div class="keywords-section">
                <h4>키워드 조합:</h4>
                <div class="keywords-list">
                    ${link.keywords.map(kw => `
                        <div class="keyword-item">
                            <span class="query-keyword">query: ${kw.query_keyword}</span>
                            <span class="acq-keyword">acq: ${kw.acq_keyword}</span>
                            <button class="btn-delete-keyword" onclick="deleteKeyword(${link.link_id}, ${kw.keyword_id})" title="삭제">
                                🗑️
                            </button>
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
    `).join('');
}

// 링크 복사
async function copyLink(shortCode) {
    const fullUrl = `${window.location.origin}/redirect/${shortCode}`;
    
    try {
        await navigator.clipboard.writeText(fullUrl);
        showMessage('링크가 클립보드에 복사되었습니다.', 'success');
    } catch (error) {
        // Fallback for older browsers
        const textArea = document.createElement('textarea');
        textArea.value = fullUrl;
        document.body.appendChild(textArea);
        textArea.select();
        try {
            document.execCommand('copy');
            showMessage('링크가 클립보드에 복사되었습니다.', 'success');
        } catch (err) {
            showMessage('링크 복사에 실패했습니다.', 'error');
        }
        document.body.removeChild(textArea);
    }
}

// 새 링크 생성 폼 표시
function showCreateLinkForm() {
    const modal = document.getElementById('linkModal');
    if (!modal) return;
    
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h2>새 링크 생성</h2>
                <button class="btn-close" onclick="closeModal()">×</button>
            </div>
            <div class="modal-body">
                <form id="createLinkForm">
                    <div class="form-group">
                        <label for="productName">상품명 (선택사항)</label>
                        <input type="text" id="productName" name="productName" placeholder="상품명을 입력하세요">
                    </div>
                    <div class="form-group">
                        <label>키워드 조합</label>
                        <div id="keywordsContainer">
                            <div class="keyword-input-row">
                                <input type="text" name="query_keyword" placeholder="query 키워드" required>
                                <input type="text" name="acq_keyword" placeholder="acq 키워드" required>
                                <button type="button" class="btn-remove-keyword" onclick="removeKeywordRow(this)">삭제</button>
                            </div>
                        </div>
                        <button type="button" class="btn-add-keyword" onclick="addKeywordRow()">+ 키워드 추가</button>
                    </div>
                    <div class="form-actions">
                        <button type="submit" class="btn-primary">생성</button>
                        <button type="button" class="btn-secondary" onclick="closeModal()">취소</button>
                    </div>
                </form>
            </div>
        </div>
    `;
    
    modal.style.display = 'block';
    
    document.getElementById('createLinkForm').addEventListener('submit', handleCreateLink);
}

// 키워드 행 추가
function addKeywordRow() {
    const container = document.getElementById('keywordsContainer');
    if (!container) return;
    
    const row = document.createElement('div');
    row.className = 'keyword-input-row';
    row.innerHTML = `
        <input type="text" name="query_keyword" placeholder="query 키워드" required>
        <input type="text" name="acq_keyword" placeholder="acq 키워드" required>
        <button type="button" class="btn-remove-keyword" onclick="removeKeywordRow(this)">삭제</button>
    `;
    container.appendChild(row);
}

// 키워드 행 삭제
function removeKeywordRow(button) {
    button.parentElement.remove();
}

// 링크 생성 처리
async function handleCreateLink(event) {
    event.preventDefault();
    
    const form = event.target;
    const formData = new FormData(form);
    
    const productName = document.getElementById('productName').value;
    const queryKeywords = form.querySelectorAll('input[name="query_keyword"]');
    const acqKeywords = form.querySelectorAll('input[name="acq_keyword"]');
    
    if (queryKeywords.length !== acqKeywords.length) {
        showMessage('키워드 조합이 올바르지 않습니다.', 'error');
        return;
    }
    
    const keywords = [];
    for (let i = 0; i < queryKeywords.length; i++) {
        const query = queryKeywords[i].value.trim();
        const acq = acqKeywords[i].value.trim();
        
        if (query && acq) {
            keywords.push({
                query_keyword: query,
                acq_keyword: acq
            });
        }
    }
    
    if (keywords.length === 0) {
        showMessage('최소 1개의 키워드 조합이 필요합니다.', 'error');
        return;
    }
    
    try {
        const data = await apiCall(`${API_BASE_URL}/rewards/links`, {
            method: 'POST',
            body: JSON.stringify({
                product_name: productName || null,
                keywords: keywords
            })
        });
        
        if (data.success) {
            showMessage('링크가 생성되었습니다.', 'success');
            closeModal();
            loadLinks();
        } else {
            showMessage(data.detail || '링크 생성에 실패했습니다.', 'error');
        }
    } catch (error) {
        showMessage(error.message || '링크 생성에 실패했습니다.', 'error');
    }
}

// 링크 수정
async function editLink(linkId) {
    try {
        const linksData = await apiCall(`${API_BASE_URL}/rewards/links`);
        const link = linksData.data.links.find(l => l.link_id === linkId);
        
        if (!link) {
            showMessage('링크를 찾을 수 없습니다.', 'error');
            return;
        }
        
        const modal = document.getElementById('linkModal');
        if (!modal) return;
        
        modal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h2>링크 수정</h2>
                    <button class="btn-close" onclick="closeModal()">×</button>
                </div>
                <div class="modal-body">
                    <form id="editLinkForm">
                        <div class="form-group">
                            <label for="editProductName">상품명</label>
                            <input type="text" id="editProductName" name="productName" value="${link.product_name || ''}" placeholder="상품명을 입력하세요">
                        </div>
                        <div class="form-group">
                            <label>키워드 조합</label>
                            <div id="editKeywordsContainer">
                                ${link.keywords.map(kw => `
                                    <div class="keyword-input-row">
                                        <input type="text" name="query_keyword" value="${kw.query_keyword}" placeholder="query 키워드" required>
                                        <input type="text" name="acq_keyword" value="${kw.acq_keyword}" placeholder="acq 키워드" required>
                                        <button type="button" class="btn-remove-keyword" onclick="removeKeywordRow(this)">삭제</button>
                                    </div>
                                `).join('')}
                            </div>
                            <button type="button" class="btn-add-keyword" onclick="addKeywordRow()">+ 키워드 추가</button>
                        </div>
                        <div class="form-actions">
                            <button type="submit" class="btn-primary">수정</button>
                            <button type="button" class="btn-secondary" onclick="closeModal()">취소</button>
                        </div>
                    </form>
                </div>
            </div>
        `;
        
        modal.style.display = 'block';
        
        document.getElementById('editLinkForm').addEventListener('submit', (e) => handleEditLink(e, linkId));
    } catch (error) {
        showMessage('링크 정보를 불러오는데 실패했습니다.', 'error');
    }
}

// 링크 수정 처리
async function handleEditLink(event, linkId) {
    event.preventDefault();
    
    const form = event.target;
    const productName = document.getElementById('editProductName').value;
    const queryKeywords = form.querySelectorAll('input[name="query_keyword"]');
    const acqKeywords = form.querySelectorAll('input[name="acq_keyword"]');
    
    const keywords = [];
    for (let i = 0; i < queryKeywords.length; i++) {
        const query = queryKeywords[i].value.trim();
        const acq = acqKeywords[i].value.trim();
        
        if (query && acq) {
            keywords.push({
                query_keyword: query,
                acq_keyword: acq
            });
        }
    }
    
    try {
        const data = await apiCall(`${API_BASE_URL}/rewards/links/${linkId}`, {
            method: 'PUT',
            body: JSON.stringify({
                product_name: productName || null,
                keywords: keywords
            })
        });
        
        if (data.success) {
            showMessage('링크가 수정되었습니다.', 'success');
            closeModal();
            loadLinks();
        } else {
            showMessage(data.detail || '링크 수정에 실패했습니다.', 'error');
        }
    } catch (error) {
        showMessage(error.message || '링크 수정에 실패했습니다.', 'error');
    }
}

// 키워드 추가
async function addKeywordToLink(linkId) {
    const query = prompt('query 키워드를 입력하세요:');
    if (!query) return;
    
    const acq = prompt('acq 키워드를 입력하세요:');
    if (!acq) return;
    
    try {
        const data = await apiCall(`${API_BASE_URL}/rewards/links/${linkId}/keywords`, {
            method: 'POST',
            body: JSON.stringify({
                query_keyword: query,
                acq_keyword: acq
            })
        });
        
        if (data.success) {
            showMessage('키워드가 추가되었습니다.', 'success');
            loadLinks();
        } else {
            showMessage(data.detail || '키워드 추가에 실패했습니다.', 'error');
        }
    } catch (error) {
        showMessage(error.message || '키워드 추가에 실패했습니다.', 'error');
    }
}

// 키워드 삭제
async function deleteKeyword(linkId, keywordId) {
    if (!confirm('이 키워드를 삭제하시겠습니까?')) return;
    
    try {
        const data = await apiCall(`${API_BASE_URL}/rewards/links/${linkId}/keywords/${keywordId}`, {
            method: 'DELETE'
        });
        
        if (data.success) {
            showMessage('키워드가 삭제되었습니다.', 'success');
            loadLinks();
        } else {
            showMessage(data.detail || '키워드 삭제에 실패했습니다.', 'error');
        }
    } catch (error) {
        showMessage(error.message || '키워드 삭제에 실패했습니다.', 'error');
    }
}

// 링크 삭제
async function deleteLink(linkId) {
    if (!confirm('이 링크를 삭제하시겠습니까? 관련된 모든 키워드도 함께 삭제됩니다.')) return;
    
    try {
        const data = await apiCall(`${API_BASE_URL}/rewards/links/${linkId}`, {
            method: 'DELETE'
        });
        
        if (data.success) {
            showMessage('링크가 삭제되었습니다.', 'success');
            loadLinks();
        } else {
            showMessage(data.detail || '링크 삭제에 실패했습니다.', 'error');
        }
    } catch (error) {
        showMessage(error.message || '링크 삭제에 실패했습니다.', 'error');
    }
}

// 모달 닫기
function closeModal() {
    const modal = document.getElementById('linkModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// 메시지 표시
function showMessage(message, type = 'info') {
    // 간단한 알림 구현 (실제 프로젝트에서는 더 나은 UI 사용)
    alert(message);
}

// 페이지 로드 시 초기화
document.addEventListener('DOMContentLoaded', () => {
    loadLinks();
    
    const createBtn = document.getElementById('createLinkBtn');
    if (createBtn) {
        createBtn.addEventListener('click', showCreateLinkForm);
    }
    
    // 모달 외부 클릭 시 닫기
    const modal = document.getElementById('linkModal');
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModal();
            }
        });
    }
});
