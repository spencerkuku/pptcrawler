import requests
from bs4 import BeautifulSoup
import re
import json
import time
import os
import sys
import argparse
import concurrent.futures
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Union
import logging
from urllib.parse import urljoin
import yaml

# 進度條庫
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("建議安裝 tqdm 來顯示進度條: pip install tqdm")

# pandas for CSV export
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

@dataclass
class Article:
    """文章數據結構"""
    board: str
    article_id: str
    title: str
    author: str
    date: str
    content: str
    url: str
    ip: str = "Unknown"
    push_count: int = 0
    boo_count: int = 0
    neutral_count: int = 0
    total_messages: int = 0
    messages: List[Dict] = None
    crawl_time: str = ""
    
    def __post_init__(self):
        if self.messages is None:
            self.messages = []
        if not self.crawl_time:
            self.crawl_time = datetime.now().isoformat()

@dataclass
class CrawlConfig:
    """爬蟲配置"""
    delay_between_requests: float = 0.1
    delay_between_pages: float = 0.5
    timeout: int = 10
    max_retries: int = 3
    max_workers: int = 4
    output_dir: str = "./crawled_data"
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    
    @classmethod
    def from_file(cls, config_path: str) -> 'CrawlConfig':
        """從配置文件載入"""
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
                return cls(**config_data)
        return cls()
    
    def save_to_file(self, config_path: str):
        """保存配置到文件"""
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(asdict(self), f, default_flow_style=False, allow_unicode=True)

class PTTCrawler:
    """PTT 爬蟲主類別"""
    
    def __init__(self, config: CrawlConfig = None):
        self.config = config or CrawlConfig()
        self.session = self._create_session()
        self.logger = self._setup_logger()
        
        # 確保輸出目錄存在
        Path(self.config.output_dir).mkdir(parents=True, exist_ok=True)
    
    def _create_session(self) -> requests.Session:
        """創建請求會話"""
        session = requests.Session()
        session.headers.update({
            'User-Agent': self.config.user_agent
        })
        session.cookies.update({'over18': '1'})  # 年齡驗證
        return session
    
    def _setup_logger(self) -> logging.Logger:
        """設置日誌"""
        logger = logging.getLogger('PTTCrawler')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def _make_request(self, url: str, retries: int = None) -> Optional[requests.Response]:
        """帶重試機制的請求"""
        max_retries = retries or self.config.max_retries
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, timeout=self.config.timeout)
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                self.logger.warning(f"請求失敗 (第 {attempt + 1} 次): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # 指數退避
                else:
                    self.logger.error(f"請求最終失敗: {url}")
                    return None
    
    def get_latest_page_number(self, board_name: str) -> int:
        """獲取看板最新頁數"""
        url = f"https://www.ptt.cc/bbs/{board_name}/index.html"
        response = self._make_request(url)
        
        if not response:
            return 0
        
        # 方法1: 查找上一頁連結
        pattern = rf'href="/bbs/{board_name}/index(\d+)\.html">&lsaquo;'
        match = re.search(pattern, response.text)
        if match:
            return int(match.group(1)) + 1
        
        # 方法2: 解析所有頁數連結
        soup = BeautifulSoup(response.text, 'html.parser')
        page_numbers = soup.find_all('a', href=re.compile(rf'/{board_name}/index(\d+)\.html'))
        
        if page_numbers:
            pages = [int(p.get('href').split('index')[1].replace('.html', '')) 
                    for p in page_numbers]
            return max(pages)
        
        return 0
    
    def extract_articles_from_page(self, board_name: str, page_num: int) -> List[Dict]:
        """從指定頁面提取文章基本信息"""
        url = f"https://www.ptt.cc/bbs/{board_name}/index{page_num}.html"
        response = self._make_request(url)
        
        if not response:
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = []
        
        for div in soup.find_all("div", class_="r-ent"):
            link_elem = div.find('a')
            if not link_elem or not link_elem.get('href'):
                continue
            
            href = link_elem['href']
            article_url = urljoin("https://www.ptt.cc", href)
            article_id = href.split('/')[-1].replace('.html', '')
            title = link_elem.get_text(strip=True)
            
            # 提取作者和日期
            author_elem = div.find('div', class_='author')
            date_elem = div.find('div', class_='date')
            
            # 提取推文數
            push_elem = div.find('div', class_='nrec')
            push_text = push_elem.get_text(strip=True) if push_elem else ''
            
            articles.append({
                'board': board_name,
                'article_id': article_id,
                'title': title,
                'author': author_elem.get_text(strip=True) if author_elem else '',
                'date': date_elem.get_text(strip=True) if date_elem else '',
                'url': article_url,
                'push_preview': push_text
            })
        
        return articles
    
    def parse_article_content(self, article_url: str) -> Optional[Dict]:
        """解析單篇文章詳細內容"""
        response = self._make_request(article_url)
        if not response:
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        main_content = soup.find(id="main-content")
        
        if not main_content:
            self.logger.warning(f"找不到文章內容: {article_url}")
            return None
        
        # 解析 metadata
        metas = main_content.select('div.article-metaline')
        author = title = date = ''
        
        if len(metas) >= 3:
            try:
                author = metas[0].select('span.article-meta-value')[0].get_text(strip=True)
                title = metas[1].select('span.article-meta-value')[0].get_text(strip=True)
                date = metas[2].select('span.article-meta-value')[0].get_text(strip=True)
            except (IndexError, AttributeError):
                pass
        
        # 移除 metadata
        for meta in metas:
            meta.extract()
        for meta in main_content.select('div.article-metaline-right'):
            meta.extract()
        
        # 解析推文
        pushes = main_content.find_all('div', class_='push')
        messages = []
        push_count = boo_count = neutral_count = 0
        
        for push in pushes:
            push.extract()
            
            try:
                tag_elem = push.find('span', 'push-tag')
                userid_elem = push.find('span', 'push-userid')
                content_elem = push.find('span', 'push-content')
                datetime_elem = push.find('span', 'push-ipdatetime')
                
                if all([tag_elem, userid_elem, content_elem, datetime_elem]):
                    tag = tag_elem.get_text(strip=True)
                    userid = userid_elem.get_text(strip=True)
                    content = content_elem.get_text(strip=True)
                    datetime_str = datetime_elem.get_text(strip=True)
                    
                    if content.startswith(':'):
                        content = content[1:].strip()
                    
                    # 解析 IP 和時間
                    ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
                    ip_match = re.search(ip_pattern, datetime_str)
                    
                    if ip_match:
                        ip = ip_match.group()
                        datetime_clean = datetime_str.replace(ip, '').strip()
                    else:
                        ip = "Unknown"
                        datetime_clean = datetime_str
                    
                    messages.append({
                        'push_tag': tag,
                        'push_userid': userid,
                        'push_content': content,
                        'push_ip': ip,
                        'push_datetime': datetime_clean
                    })
                    
                    # 統計推文類型
                    if tag == '推':
                        push_count += 1
                    elif tag == '噓':
                        boo_count += 1
                    else:
                        neutral_count += 1
            except Exception:
                continue
        
        # 提取文章內容
        content_strings = []
        for string in main_content.stripped_strings:
            if (string.startswith('※') or 
                string.startswith('◆') or 
                string.startswith('--')):
                continue
            content_strings.append(string.strip())
        
        content = ' '.join(content_strings)
        content = re.sub(r'\s+', ' ', content).strip()
        
        # 提取發文者 IP
        ip = "Unknown"
        try:
            for string in main_content.strings:
                if '※ 發信站:' in string:
                    ip_match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', string)
                    if ip_match:
                        ip = ip_match.group()
                        break
        except:
            pass
        
        return {
            'title': title,
            'author': author,
            'date': date,
            'content': content,
            'ip': ip,
            'push_count': push_count,
            'boo_count': boo_count,
            'neutral_count': neutral_count,
            'total_messages': push_count + boo_count + neutral_count,
            'messages': messages
        }
    
    def crawl_single_article(self, board_name: str, article_id: str) -> Optional[Article]:
        """爬取單篇文章"""
        if article_id.endswith('.html'):
            url = f"https://www.ptt.cc/bbs/{board_name}/{article_id}"
        else:
            url = f"https://www.ptt.cc/bbs/{board_name}/{article_id}.html"
        
        self.logger.info(f"正在爬取文章: {url}")
        
        # 首先獲取基本信息
        basic_info = {
            'board': board_name,
            'article_id': article_id,
            'url': url
        }
        
        # 獲取詳細內容
        detailed_content = self.parse_article_content(url)
        
        if detailed_content:
            # 合併信息創建 Article 對象
            article_data = {**basic_info, **detailed_content}
            article = Article(**article_data)
            return article
        
        return None
    
    def crawl_pages_range(self, board_name: str, start_page: int, end_page: int, 
                         include_content: bool = True) -> List[Article]:
        """爬取頁面範圍"""
        self.logger.info(f"開始爬取 {board_name} 看板，頁面 {start_page} 到 {end_page}")
        
        all_articles = []
        total_pages = end_page - start_page + 1
        
        # 使用進度條
        page_iterator = range(start_page, end_page + 1)
        if HAS_TQDM:
            page_iterator = tqdm(page_iterator, desc="爬取頁面")
        
        for page in page_iterator:
            if HAS_TQDM:
                page_iterator.set_description(f"爬取第 {page} 頁")
            else:
                self.logger.info(f"正在爬取第 {page} 頁...")
            
            articles_basic = self.extract_articles_from_page(board_name, page)
            
            if include_content:
                # 並發爬取文章內容
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                    future_to_article = {
                        executor.submit(self.parse_article_content, article['url']): article
                        for article in articles_basic
                    }
                    
                    for future in concurrent.futures.as_completed(future_to_article):
                        basic_info = future_to_article[future]
                        try:
                            detailed_content = future.result()
                            if detailed_content:
                                article_data = {**basic_info, **detailed_content}
                                article = Article(**article_data)
                                all_articles.append(article)
                        except Exception as exc:
                            self.logger.error(f"文章 {basic_info['url']} 爬取失敗: {exc}")
            else:
                # 只獲取基本信息
                for basic_info in articles_basic:
                    article = Article(
                        board=basic_info['board'],
                        article_id=basic_info['article_id'],
                        title=basic_info['title'],
                        author=basic_info['author'],
                        date=basic_info['date'],
                        url=basic_info['url'],
                        content=""
                    )
                    all_articles.append(article)
            
            time.sleep(self.config.delay_between_pages)
        
        self.logger.info(f"爬取完成！共獲得 {len(all_articles)} 篇文章")
        return all_articles
    
    def search_articles(self, board_name: str, keyword: str, max_pages: int = 5) -> List[Dict]:
        """搜尋包含關鍵字的文章"""
        self.logger.info(f"在 {board_name} 看板搜尋關鍵字: {keyword}")
        
        latest_page = self.get_latest_page_number(board_name)
        start_page = max(1, latest_page - max_pages + 1)
        
        found_articles = []
        
        for page in range(start_page, latest_page + 1):
            articles = self.extract_articles_from_page(board_name, page)
            
            for article in articles:
                if keyword.lower() in article['title'].lower():
                    found_articles.append(article)
                    self.logger.info(f"找到: {article['title']}")
            
            time.sleep(self.config.delay_between_requests)
        
        self.logger.info(f"搜尋完成，共找到 {len(found_articles)} 篇相關文章")
        return found_articles
    
    def save_articles(self, articles: List[Article], filename: str = None) -> str:
        """保存文章到 JSON 文件"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"articles_{timestamp}.json"
        
        filepath = Path(self.config.output_dir) / filename
        
        data = {
            'articles': [asdict(article) for article in articles],
            'crawl_time': datetime.now().isoformat(),
            'total_articles': len(articles),
            'config': asdict(self.config)
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"文章已保存至: {filepath}")
        return str(filepath)
    
    def export_to_csv(self, articles: List[Article], filename: str = None) -> str:
        """導出為 CSV 格式"""
        if not HAS_PANDAS:
            raise ImportError("需要安裝 pandas: pip install pandas")
        
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"articles_{timestamp}.csv"
        
        filepath = Path(self.config.output_dir) / filename
        
        # 準備數據
        csv_data = []
        for article in articles:
            csv_data.append({
                'board': article.board,
                'article_id': article.article_id,
                'title': article.title,
                'author': article.author,
                'date': article.date,
                'content': article.content,
                'ip': article.ip,
                'push_count': article.push_count,
                'boo_count': article.boo_count,
                'neutral_count': article.neutral_count,
                'total_messages': article.total_messages,
                'url': article.url,
                'crawl_time': article.crawl_time
            })
        
        df = pd.DataFrame(csv_data)
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        
        self.logger.info(f"CSV 文件已保存至: {filepath}")
        return str(filepath)

class PTTCrawlerCLI:
    """命令行界面"""
    
    def __init__(self):
        self.config = CrawlConfig()
        self.crawler = PTTCrawler(self.config)
    
    def show_menu(self):
        """顯示主選單"""
        print("\n" + "="*50)
        print("PTT 爬蟲工具")
        print("="*50)
        print("1. 查看看板最新頁數和文章預覽")
        print("2. 爬取指定頁面範圍 (完整內容)")
        print("3. 爬取單篇文章")
        print("4. 關鍵字搜尋文章")
        print("5. 顯示指定頁面的文章列表")
        print("6. 導出已爬取的 JSON 為 CSV")
        print("7. 配置設定")
        print("8. 批量爬取最新文章")
        print("9. 退出")
        print("="*50)
    
    def handle_menu_choice(self, choice: str) -> bool:
        """處理選單選擇"""
        try:
            if choice == '1':
                self._show_board_preview()
            elif choice == '2':
                self._crawl_pages_range()
            elif choice == '3':
                self._crawl_single_article()
            elif choice == '4':
                self._search_articles()
            elif choice == '5':
                self._show_page_articles()
            elif choice == '6':
                self._convert_json_to_csv()
            elif choice == '7':
                self._configure_settings()
            elif choice == '8':
                self._batch_crawl_latest()
            elif choice == '9':
                print("👋 謝謝使用！")
                return False
            else:
                print("❌ 無效的選擇，請重新輸入")
        except KeyboardInterrupt:
            print("\n⏹️  操作已取消")
        except Exception as e:
            print(f"❌ 發生錯誤: {e}")
        
        return True
    
    def _show_board_preview(self):
        """顯示看板預覽"""
        board_name = input("請輸入看板名稱: ").strip()
        
        latest_page = self.crawler.get_latest_page_number(board_name)
        if latest_page <= 0:
            print("❌ 無法獲取看板信息")
            return
        
        print(f"\n📊 {board_name} 看板信息:")
        print(f"最新頁數: {latest_page}")
        
        articles = self.crawler.extract_articles_from_page(board_name, latest_page)
        
        if articles:
            print(f"\n📄 最新頁面文章預覽 (共 {len(articles)} 篇):")
            print("-" * 80)
            for i, article in enumerate(articles[:10], 1):
                print(f"{i:2d}. ID: {article['article_id']}")
                print(f"    📝 {article['title']}")
                print(f"    👤 {article['author']} | 📅 {article['date']} | 👍 {article['push_preview']}")
                print("-" * 80)
        
    def _crawl_pages_range(self):
        """爬取頁面範圍"""
        board_name = input("請輸入看板名稱: ").strip()
        
        try:
            start_page = int(input("請輸入起始頁數: "))
            end_page = int(input("請輸入結束頁數: "))
            
            if start_page > end_page:
                print("❌ 起始頁數不能大於結束頁數")
                return
            
            include_content = input("是否包含完整內容? (y/n): ").lower() == 'y'
            
            articles = self.crawler.crawl_pages_range(board_name, start_page, end_page, include_content)
            
            if articles:
                filename = f"{board_name}-{start_page}-{end_page}.json"
                filepath = self.crawler.save_articles(articles, filename)
                print(f"✅ 成功爬取 {len(articles)} 篇文章")
                
                if input("是否也導出為 CSV? (y/n): ").lower() == 'y':
                    csv_file = filename.replace('.json', '.csv')
                    self.crawler.export_to_csv(articles, csv_file)
        
        except ValueError:
            print("❌ 請輸入有效的數字")
    
    def _crawl_single_article(self):
        """爬取單篇文章"""
        board_name = input("請輸入看板名稱: ").strip()
        article_id = input("請輸入文章ID: ").strip()
        
        article = self.crawler.crawl_single_article(board_name, article_id)
        
        if article:
            filename = f"{board_name}-{article_id}.json"
            self.crawler.save_articles([article], filename)
            print(f"✅ 文章爬取成功")
            print(f"📝 標題: {article.title}")
            print(f"👤 作者: {article.author}")
            print(f"👍 推文統計: 推{article.push_count} 噓{article.boo_count} 中性{article.neutral_count}")
        else:
            print("❌ 文章爬取失敗")
    
    def _search_articles(self):
        """搜尋文章"""
        board_name = input("請輸入看板名稱: ").strip()
        keyword = input("請輸入關鍵字: ").strip()
        max_pages = int(input("搜尋最近幾頁? (預設5): ") or "5")
        
        found_articles = self.crawler.search_articles(board_name, keyword, max_pages)
        
        if found_articles:
            print(f"\n🔍 找到 {len(found_articles)} 篇相關文章:")
            for i, article in enumerate(found_articles, 1):
                print(f"{i}. {article['title']} - {article['author']}")
                print(f"   ID: {article['article_id']}")
    
    def _show_page_articles(self):
        """顯示頁面文章"""
        board_name = input("請輸入看板名稱: ").strip()
        try:
            page_num = int(input("請輸入頁數: "))
            articles = self.crawler.extract_articles_from_page(board_name, page_num)
            
            if articles:
                print(f"\n📄 {board_name} 看板第 {page_num} 頁 (共 {len(articles)} 篇):")
                print("-" * 80)
                for i, article in enumerate(articles, 1):
                    print(f"{i:2d}. ID: {article['article_id']}")
                    print(f"    📝 {article['title']}")
                    print(f"    👤 {article['author']} | 📅 {article['date']}")
                    print("-" * 80)
        except ValueError:
            print("❌ 請輸入有效的頁數")
    
    def _convert_json_to_csv(self):
        """轉換 JSON 到 CSV"""
        if not HAS_PANDAS:
            print("❌ 需要安裝 pandas: pip install pandas")
            return
        
        json_file = input("請輸入 JSON 文件路徑: ").strip()
        
        if not os.path.exists(json_file):
            print("❌ 文件不存在")
            return
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            articles_data = data.get('articles', [])
            articles = [Article(**article_data) for article_data in articles_data]
            
            csv_file = json_file.replace('.json', '.csv')
            self.crawler.export_to_csv(articles, csv_file)
            
        except Exception as e:
            print(f"❌ 轉換失敗: {e}")
    
    def _configure_settings(self):
        """配置設定"""
        print("\n⚙️  當前設定:")
        print(f"請求間隔: {self.config.delay_between_requests} 秒")
        print(f"頁面間隔: {self.config.delay_between_pages} 秒")
        print(f"並發數: {self.config.max_workers}")
        print(f"重試次數: {self.config.max_retries}")
        print(f"輸出目錄: {self.config.output_dir}")
        
        if input("\n是否修改設定? (y/n): ").lower() == 'y':
            try:
                self.config.delay_between_requests = float(
                    input(f"請求間隔 ({self.config.delay_between_requests}): ") 
                    or self.config.delay_between_requests
                )
                self.config.delay_between_pages = float(
                    input(f"頁面間隔 ({self.config.delay_between_pages}): ") 
                    or self.config.delay_between_pages
                )
                self.config.max_workers = int(
                    input(f"並發數 ({self.config.max_workers}): ") 
                    or self.config.max_workers
                )
                
                # 重新創建 crawler
                self.crawler = PTTCrawler(self.config)
                print("✅ 設定已更新")
                
            except ValueError:
                print("❌ 輸入格式錯誤")
    
    def _batch_crawl_latest(self):
        """批量爬取最新文章"""
        board_name = input("請輸入看板名稱: ").strip()
        num_pages = int(input("爬取最新幾頁? (預設3): ") or "3")
        
        latest_page = self.crawler.get_latest_page_number(board_name)
        start_page = max(1, latest_page - num_pages + 1)
        
        print(f"將爬取第 {start_page} 到 {latest_page} 頁")
        
        if input("確認執行? (y/n): ").lower() == 'y':
            articles = self.crawler.crawl_pages_range(board_name, start_page, latest_page)
            
            if articles:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{board_name}_latest_{timestamp}.json"
                self.crawler.save_articles(articles, filename)
                
                print(f"✅ 批量爬取完成，共 {len(articles)} 篇文章")
    
    def run(self):
        """運行命令行界面"""
        print("🚀 歡迎使用 PTT 爬蟲工具!")
        
        while True:
            try:
                self.show_menu()
                choice = input("請選擇功能 (1-9): ").strip()
                
                if not self.handle_menu_choice(choice):
                    break
                    
                input("\n按 Enter 繼續...")
                
            except KeyboardInterrupt:
                print("\n\n👋 再見!")
                break

def main():
    """主函數 - 支持命令行參數"""
    parser = argparse.ArgumentParser(description='PTT 爬蟲工具')
    parser.add_argument('--board', help='看板名稱')
    parser.add_argument('--pages', help='頁面範圍 (格式: start-end)')
    parser.add_argument('--article', help='單篇文章ID')
    parser.add_argument('--search', help='搜尋關鍵字')
    parser.add_argument('--config', help='配置文件路徑')
    parser.add_argument('--output', help='輸出目錄')
    
    args = parser.parse_args()
    
    # 載入配置
    config = CrawlConfig()
    if args.config and os.path.exists(args.config):
        config = CrawlConfig.from_file(args.config)
    
    if args.output:
        config.output_dir = args.output
    
    crawler = PTTCrawler(config)
    
    # 命令行模式
    if args.board:
        if args.pages:
            start, end = map(int, args.pages.split('-'))
            articles = crawler.crawl_pages_range(args.board, start, end)
            if articles:
                filename = f"{args.board}-{start}-{end}.json"
                crawler.save_articles(articles, filename)
        
        elif args.article:
            article = crawler.crawl_single_article(args.board, args.article)
            if article:
                crawler.save_articles([article], f"{args.board}-{args.article}.json")
        
        elif args.search:
            found = crawler.search_articles(args.board, args.search)
            for article in found:
                print(f"{article['title']} - {article['author']}")
    
    else:
        # 交互模式
        cli = PTTCrawlerCLI()
        cli.run()

if __name__ == "__main__":
    main()
