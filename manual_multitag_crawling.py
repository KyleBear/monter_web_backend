"""
구간별 리워드 랭크 태그 크롤링 수동 실행 스크립트 (GUI 버전)
- reward_rank 테이블의 특정 구간(reward_id 범위)에 대한 태그 및 이미지 URL 크롤링 수행
- 구간별로 배치 처리하여 효율적으로 크롤링
- 브라우저 병렬 실행 지원
- Command line argument 지원: --start-id, --end-id, --headless, --workers, --no-gui
"""
import logging
import sys
import os
import threading
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from tkinter import Tk, Label, Button, Entry, Text, Scrollbar, Frame, StringVar, IntVar, Checkbutton, messagebox
from tkinter import ttk
import queue

# 프로젝트 루트를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# 구간별 범위 정보
RANGE_INFO = {
    1: (1, 200),
    2: (201, 400),
    3: (401, 600),
    4: (601, 800),
    5: (801, 1000)
}


class TagCrawlingGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("구간별 리워드 랭크 태그 크롤링")
        self.root.geometry("800x700")
        
        # 실행 상태
        self.is_running = False
        self.crawling_thread = None
        
        # 로그 큐 (스레드 간 통신)
        self.log_queue = queue.Queue()
        
        self.setup_ui()
        self.process_log_queue()
        
    def setup_ui(self):
        """UI 구성"""
        # 메인 프레임
        main_frame = Frame(self.root, padx=10, pady=10)
        main_frame.pack(fill='both', expand=True)
        
        # 제목
        title_label = Label(main_frame, text="구간별 리워드 랭크 태그 크롤링", font=("Arial", 16, "bold"))
        title_label.pack(pady=(0, 20))
        
        # 구간 선택 프레임
        range_frame = Frame(main_frame)
        range_frame.pack(fill='x', pady=5)
        
        Label(range_frame, text="구간 선택:", font=("Arial", 10)).pack(side='left', padx=5)
        
        self.range_var = StringVar(value="1")
        for i in range(1, 6):
            Checkbutton(
                range_frame,
                text=f"구간 {i} ({RANGE_INFO[i][0]}~{RANGE_INFO[i][1]})",
                variable=StringVar(value=str(i)),
                command=lambda idx=i: self.toggle_range(idx)
            ).pack(side='left', padx=5)
        
        # 사용자 정의 구간
        custom_frame = Frame(main_frame)
        custom_frame.pack(fill='x', pady=5)
        
        Label(custom_frame, text="사용자 정의 구간:", font=("Arial", 10)).pack(side='left', padx=5)
        Label(custom_frame, text="시작 reward_id:").pack(side='left', padx=5)
        self.start_id_entry = Entry(custom_frame, width=10)
        self.start_id_entry.pack(side='left', padx=5)
        
        Label(custom_frame, text="종료 reward_id:").pack(side='left', padx=5)
        self.end_id_entry = Entry(custom_frame, width=10)
        self.end_id_entry.pack(side='left', padx=5)
        
        # reward_id 범위 확인 버튼
        check_range_button = Button(
            custom_frame,
            text="reward_id 범위 확인",
            command=self.check_reward_id_range,
            font=("Arial", 8),
            bg="#2196F3",
            fg="white"
        )
        check_range_button.pack(side='left', padx=5)
        
        # 설정 프레임
        settings_frame = Frame(main_frame)
        settings_frame.pack(fill='x', pady=10)
        
        # Headless 모드 (기본값: True)
        self.headless_var = IntVar(value=1)  # 1 = True (체크됨)
        Checkbutton(
            settings_frame,
            text="Headless 모드 (기본값: 체크)",
            variable=self.headless_var
        ).pack(side='left', padx=5)
        
        # 병렬 작업자 수
        Label(settings_frame, text="병렬 작업자 수:").pack(side='left', padx=5)
        self.workers_var = StringVar(value="5")
        workers_entry = Entry(settings_frame, textvariable=self.workers_var, width=5)
        workers_entry.pack(side='left', padx=5)
        
        # 선택된 구간 표시
        self.selected_ranges_label = Label(main_frame, text="선택된 구간: 없음", font=("Arial", 9))
        self.selected_ranges_label.pack(pady=5)
        
        # 버튼 프레임
        button_frame = Frame(main_frame)
        button_frame.pack(fill='x', pady=10)
        
        self.start_button = Button(
            button_frame,
            text="크롤링 시작",
            command=self.start_crawling,
            bg="#4CAF50",
            fg="white",
            font=("Arial", 12, "bold"),
            width=15
        )
        self.start_button.pack(side='left', padx=5)
        
        self.stop_button = Button(
            button_frame,
            text="중지",
            command=self.stop_crawling,
            bg="#f44336",
            fg="white",
            font=("Arial", 12, "bold"),
            width=15,
            state='disabled'
        )
        self.stop_button.pack(side='left', padx=5)
        
        # 진행 상태
        self.progress_label = Label(main_frame, text="대기 중...", font=("Arial", 10))
        self.progress_label.pack(pady=5)
        
        self.progress_bar = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress_bar.pack(fill='x', pady=5)
        
        # 통계 프레임
        stats_frame = Frame(main_frame)
        stats_frame.pack(fill='x', pady=5)
        
        self.stats_label = Label(
            stats_frame,
            text="전체: 0 | 성공: 0 | 실패: 0 | 건너뜀: 0",
            font=("Arial", 9)
        )
        self.stats_label.pack()
        
        # 로그 영역
        log_frame = Frame(main_frame)
        log_frame.pack(fill='both', expand=True, pady=10)
        
        Label(log_frame, text="로그:", font=("Arial", 10, "bold")).pack(anchor='w')
        
        log_text_frame = Frame(log_frame)
        log_text_frame.pack(fill='both', expand=True)
        
        scrollbar = Scrollbar(log_text_frame)
        scrollbar.pack(side='right', fill='y')
        
        self.log_text = Text(log_text_frame, yscrollcommand=scrollbar.set, wrap='word')
        self.log_text.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=self.log_text.yview)
        
        # 선택된 구간 저장
        self.selected_ranges = []
        
    def toggle_range(self, range_num):
        """구간 선택 토글"""
        range_tuple = RANGE_INFO[range_num]
        if range_tuple in self.selected_ranges:
            self.selected_ranges.remove(range_tuple)
        else:
            self.selected_ranges.append(range_tuple)
        self.update_selected_ranges_label()
        
    def update_selected_ranges_label(self):
        """선택된 구간 라벨 업데이트"""
        if self.selected_ranges:
            ranges_str = ", ".join([f"{start}~{end}" for start, end in self.selected_ranges])
            self.selected_ranges_label.config(text=f"선택된 구간: {ranges_str}")
        else:
            self.selected_ranges_label.config(text="선택된 구간: 없음")
    
    def check_reward_id_range(self):
        """실제 reward_id 범위 확인"""
        try:
            from database_package import SessionLocal
            from models import RewardRank
            from sqlalchemy import func
            
            db = SessionLocal()
            try:
                # 최소값과 최대값 조회
                min_id = db.query(func.min(RewardRank.reward_id)).scalar()
                max_id = db.query(func.max(RewardRank.reward_id)).scalar()
                count = db.query(RewardRank).count()
                
                if min_id and max_id:
                    messagebox.showinfo(
                        "reward_id 범위 정보",
                        f"전체 레코드 수: {count:,}개\n"
                        f"최소 reward_id: {min_id}\n"
                        f"최대 reward_id: {max_id}\n\n"
                        f"사용 가능한 범위: {min_id} ~ {max_id}"
                    )
                else:
                    messagebox.showwarning("경고", "reward_rank 테이블에 데이터가 없습니다.")
            finally:
                db.close()
        except Exception as e:
            error_msg = f"reward_id 범위 확인 중 오류: {str(e)}"
            logger.error(error_msg, exc_info=True)
            messagebox.showerror("오류", error_msg)
    
    def log(self, message):
        """로그 메시지 추가"""
        self.log_queue.put(message)
    
    def process_log_queue(self):
        """로그 큐 처리 (메인 스레드에서 실행)"""
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_text.insert('end', message + '\n')
                self.log_text.see('end')
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_log_queue)
    
    def start_crawling(self):
        """크롤링 시작"""
        if self.is_running:
            return
        
        # 구간 확인
        ranges = []
        
        # 선택된 구간 추가
        if self.selected_ranges:
            ranges.extend(self.selected_ranges)
        
        # 사용자 정의 구간 추가
        try:
            start_id = self.start_id_entry.get().strip()
            end_id = self.end_id_entry.get().strip()
            if start_id and end_id:
                start_id = int(start_id)
                end_id = int(end_id)
                if start_id > end_id:
                    messagebox.showerror("오류", "시작 ID가 종료 ID보다 클 수 없습니다.")
                    return
                ranges.append((start_id, end_id))
        except ValueError:
            if start_id or end_id:
                messagebox.showerror("오류", "올바른 숫자를 입력해주세요.")
                return
        
        if not ranges:
            messagebox.showwarning("경고", "최소 하나의 구간을 선택하거나 사용자 정의 구간을 입력해주세요.")
            return
        
        # 병렬 작업자 수 확인
        try:
            max_workers = int(self.workers_var.get())
            if max_workers < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("오류", "병렬 작업자 수는 1 이상의 숫자여야 합니다.")
            return
        
        # Headless 모드
        headless = bool(self.headless_var.get())
        
        # 상태 업데이트
        self.is_running = True
        self.start_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.progress_bar.start()
        self.progress_label.config(text="크롤링 진행 중...")
        self.log_text.delete('1.0', 'end')
        
        # 크롤링 스레드 시작
        self.crawling_thread = threading.Thread(
            target=self.crawl_worker,
            args=(ranges, headless, max_workers),
            daemon=True
        )
        self.crawling_thread.start()
    
    def stop_crawling(self):
        """크롤링 중지"""
        if not self.is_running:
            return
        
        self.is_running = False
        self.log("사용자에 의해 크롤링이 중지되었습니다.")
        self.progress_bar.stop()
        self.progress_label.config(text="중지됨")
        self.start_button.config(state='normal')
        self.stop_button.config(state='disabled')
    
    def crawl_worker(self, ranges, headless, max_workers):
        """크롤링 작업자 (별도 스레드에서 실행)"""
        try:
            from api.routers.keyword_search_api2 import crawl_tags_for_range_rewards_parallel
            
            total_stats = {
                'total': 0,
                'crawled': 0,
                'failed': 0,
                'skipped': 0
            }
            
            for idx, (start_id, end_id) in enumerate(ranges, 1):
                if not self.is_running:
                    break
                
                self.log(f"\n{'='*60}")
                self.log(f"구간 {idx}/{len(ranges)}: reward_id {start_id} ~ {end_id}")
                self.log(f"{'='*60}\n")
                
                # 입력값 확인 로그
                self.log(f"[입력값 확인] 시작 reward_id: {start_id}, 종료 reward_id: {end_id}")
                
                stats = crawl_tags_for_range_rewards_parallel(
                    start_id=start_id,
                    end_id=end_id,
                    headless=headless,
                    max_workers=max_workers
                )
                
                # 조회된 레코드 수 확인 및 경고
                if stats['total'] == 0:
                    self.log(f"[경고] reward_id {start_id}~{end_id} 범위에 해당하는 레코드가 없습니다.")
                    self.log(f"       실제 reward_id 범위를 확인하려면 'reward_id 범위 확인' 버튼을 클릭하세요.")
                
                # 전체 통계 누적
                total_stats['total'] += stats['total']
                total_stats['crawled'] += stats['crawled']
                total_stats['failed'] += stats['failed']
                total_stats['skipped'] += stats['skipped']
                
                self.log(f"\n구간 {idx}/{len(ranges)} 완료:")
                self.log(f"  전체: {stats['total']}개")
                self.log(f"  성공: {stats['crawled']}개")
                self.log(f"  실패: {stats['failed']}개")
                self.log(f"  건너뜀: {stats['skipped']}개")
                
                # 통계 업데이트
                self.root.after(0, lambda: self.update_stats(total_stats))
            
            if self.is_running:
                self.log("\n" + "="*60)
                self.log("전체 크롤링 결과")
                self.log("="*60)
                self.log(f"  전체 레코드: {total_stats['total']}개")
                self.log(f"  성공: {total_stats['crawled']}개")
                self.log(f"  실패: {total_stats['failed']}개")
                self.log(f"  건너뜀: {total_stats['skipped']}개")
                self.log("="*60)
                
                messagebox.showinfo("완료", f"크롤링이 완료되었습니다.\n\n전체: {total_stats['total']}개\n성공: {total_stats['crawled']}개\n실패: {total_stats['failed']}개\n건너뜀: {total_stats['skipped']}개")
        
        except Exception as e:
            error_msg = f"오류 발생: {e}"
            self.log(error_msg)
            logger.error(error_msg, exc_info=True)
            self.root.after(0, lambda: messagebox.showerror("오류", error_msg))
        finally:
            self.root.after(0, self.crawling_finished)
    
    def update_stats(self, stats):
        """통계 업데이트"""
        self.stats_label.config(
            text=f"전체: {stats['total']} | 성공: {stats['crawled']} | 실패: {stats['failed']} | 건너뜀: {stats['skipped']}"
        )
    
    def crawling_finished(self):
        """크롤링 완료 처리"""
        self.is_running = False
        self.progress_bar.stop()
        self.progress_label.config(text="완료")
        self.start_button.config(state='normal')
        self.stop_button.config(state='disabled')


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description='구간별 리워드 랭크 태그 크롤링')
    parser.add_argument('--start-id', type=int, help='시작 reward_id')
    parser.add_argument('--end-id', type=int, help='종료 reward_id')
    parser.add_argument('--headless', action='store_true', help='Headless 모드 (기본값: True)')
    parser.add_argument('--no-headless', action='store_true', help='Headless 모드 비활성화')
    parser.add_argument('--workers', type=int, default=5, help='병렬 작업자 수 (기본값: 5)')
    parser.add_argument('--no-gui', action='store_true', help='GUI 없이 콘솔 모드로 실행')
    
    args = parser.parse_args()
    
    # Command line argument가 있으면 콘솔 모드로 실행
    if args.start_id is not None and args.end_id is not None:
        from api.routers.keyword_search_api2 import crawl_tags_for_range_rewards_parallel
        
        headless = args.headless if args.headless else (not args.no_headless)  # 기본값: True
        max_workers = args.workers
        
        print(f"\n{'='*60}")
        print(f"크롤링 시작: reward_id {args.start_id} ~ {args.end_id}")
        print(f"Headless 모드: {headless}, 병렬 작업자: {max_workers}")
        print(f"{'='*60}\n")
        
        stats = crawl_tags_for_range_rewards_parallel(
            start_id=args.start_id,
            end_id=args.end_id,
            headless=headless,
            max_workers=max_workers
        )
        
        print("\n" + "="*60)
        print("크롤링 결과")
        print("="*60)
        print(f"전체: {stats['total']}개")
        print(f"성공: {stats['crawled']}개")
        print(f"실패: {stats['failed']}개")
        print(f"건너뜀: {stats['skipped']}개")
        print("="*60)
        
        if stats.get('failed_details'):
            print("\n[실패 상세]")
            for detail in stats['failed_details']:
                print(f"  reward_id={detail['reward_id']}: {detail['reason']}")
        
        if stats.get('skipped_details'):
            print("\n[건너뛰기 상세]")
            for detail in stats['skipped_details']:
                print(f"  reward_id={detail['reward_id']}: {detail['reason']}")
        
        return
    
    # GUI 모드로 실행
    root = Tk()
    app = TagCrawlingGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
