import requests
from bs4 import BeautifulSoup
import re
import json
import time
import os
from datetime import datetime

def get_latest_index(board_name):
    base_url = f"https://www.ptt.cc/bbs/{board_name}/index.html"
    
    try:
        response = requests.get(base_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 找到頁數的部分，通常在頁面上會有特定的標籤
        page_numbers = soup.find_all('a', href=re.compile(rf'/{board_name}/index(\d+)\.html'))
        
        if not page_numbers:
            return 0
        
        # 解析所有的頁數並找到最大值
        latest_page = max([int(p.get('href').split('index')[1].replace('.html', '')) for p in page_numbers])
        return latest_page
    
    except requests.RequestException as e:
        print(f"請求發生錯誤：{e}")
        return 0

def get_session():
    """創建請求會話"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    session.cookies.update({'over18': '1'})  # 年齡驗證
    return session

def extract_article_links(board_name, page_num, session):
    """從指定頁面提取文章連結"""
    url = f"https://www.ptt.cc/bbs/{board_name}/index{page_num}.html"
    
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        articles = []
        # 找到所有文章條目
        for div in soup.find_all("div", class_="r-ent"):
            link_elem = div.find('a')
            if link_elem and link_elem.get('href'):
                href = link_elem['href']
                article_url = f"https://www.ptt.cc{href}"
                article_id = href.split('/')[-1].replace('.html', '')
                title = link_elem.get_text(strip=True)
                
                # 提取作者和日期信息
                author_elem = div.find('div', class_='author')
                date_elem = div.find('div', class_='date')
                
                articles.append({
                    'url': article_url,
                    'article_id': article_id,
                    'title': title,
                    'author': author_elem.get_text(strip=True) if author_elem else '',
                    'date': date_elem.get_text(strip=True) if date_elem else ''
                })
        
        return articles
        
    except requests.RequestException as e:
        print(f"提取文章連結時發生錯誤：{e}")
        return []

def parse_article_content(article_url, session):
    """解析單篇文章內容"""
    try:
        response = session.get(article_url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        main_content = soup.find(id="main-content")
        if not main_content:
            return None
        
        # 解析文章 metadata
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
            push.extract()  # 從主內容中移除
            
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
                    
                    # 移除內容開頭的 ':'
                    if content.startswith(':'):
                        content = content[1:].strip()
                    
                    # 解析 IP 和時間
                    ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
                    ip_match = re.search(ip_pattern, datetime_str)
                    
                    if ip_match:
                        ip = ip_match.group()
                        datetime_clean = datetime_str.replace(ip, '').strip()
                    else:
                        ip = "None"
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
            # 跳過系統訊息
            if (string.startswith('※') or 
                string.startswith('◆') or 
                string.startswith('--')):
                continue
            content_strings.append(string.strip())
        
        content = ' '.join(content_strings)
        content = re.sub(r'\s+', ' ', content).strip()
        
        # 提取 IP
        ip = "None"
        try:
            for string in main_content.strings:
                if '※ 發信站:' in string:
                    ip_match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', string)
                    if ip_match:
                        ip = ip_match.group()
                        break
        except:
            pass
        
        # 統計推文
        total = push_count + boo_count + neutral_count
        message_count = {
            'all': total,
            'count': push_count - boo_count,
            'push': push_count,
            'boo': boo_count,
            'neutral': neutral_count
        }
        
        return {
            'url': article_url,
            'article_title': title,
            'author': author,
            'date': date,
            'content': content,
            'ip': ip,
            'message_count': message_count,
            'messages': messages
        }
        
    except Exception as e:
        print(f"解析文章內容時發生錯誤：{e}")
        return None

def crawl_board_pages(board_name, start_page, end_page, output_dir="./crawled_data"):
    """爬取指定範圍的頁面"""
    os.makedirs(output_dir, exist_ok=True)
    session = get_session()
    
    all_articles = []
    
    for page in range(start_page, end_page + 1):
        print(f"正在爬取第 {page} 頁...")
        
        # 獲取文章列表
        articles = extract_article_links(board_name, page, session)
        
        for article in articles:
            print(f"  正在處理文章: {article['title']}")
            
            # 解析文章內容
            content = parse_article_content(article['url'], session)
            if content:
                # 合併基本信息和內容
                full_article = {
                    'board': board_name,
                    'article_id': article['article_id'],
                    **content
                }
                all_articles.append(full_article)
            
            # 延遲避免過於頻繁的請求
            time.sleep(0.1)
        
        # 頁面間延遲
        time.sleep(0.5)
    
    # 保存結果
    filename = f"{board_name}-{start_page}-{end_page}.json"
    filepath = os.path.join(output_dir, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump({
            'articles': all_articles,
            'crawl_time': datetime.now().isoformat(),
            'total_articles': len(all_articles)
        }, f, ensure_ascii=False, indent=2)
    
    print(f"爬取完成！共 {len(all_articles)} 篇文章，已保存至 {filepath}")
    return filepath

def crawl_single_article(board_name, article_id, output_dir="./crawled_data"):
    """爬取單篇文章"""
    os.makedirs(output_dir, exist_ok=True)
    session = get_session()
    
    # 處理文章ID，如果已經包含.html則不再添加
    if article_id.endswith('.html'):
        url = f"https://www.ptt.cc/bbs/{board_name}/{article_id}"
    else:
        url = f"https://www.ptt.cc/bbs/{board_name}/{article_id}.html"
    
    print(f"正在爬取文章: {url}")
    
    content = parse_article_content(url, session)
    if content:
        article_data = {
            'board': board_name,
            'article_id': article_id,
            **content
        }
        
        filename = f"{board_name}-{article_id}.json"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(article_data, f, ensure_ascii=False, indent=2)
        
        print(f"文章已保存至 {filepath}")
        return filepath
    else:
        print("文章爬取失敗")
        return None

def get_latest_index_improved(board_name):
    """改進版的獲取最新頁數功能"""
    session = get_session()
    url = f"https://www.ptt.cc/bbs/{board_name}/index.html"
    
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        
        # 查找上一頁的連結來確定最新頁數
        pattern = rf'href="/bbs/{board_name}/index(\d+)\.html">&lsaquo;'
        match = re.search(pattern, response.text)
        
        if match:
            return int(match.group(1)) + 1
        else:
            # 如果找不到上一頁連結，嘗試原來的方法
            return get_latest_index(board_name)
            
    except requests.RequestException as e:
        print(f"獲取最新頁數時發生錯誤：{e}")
        return get_latest_index(board_name)  # 回退到原來的方法

def show_board_info(board_name):
    """顯示看板詳細信息"""
    session = get_session()
    url = f"https://www.ptt.cc/bbs/{board_name}/index.html"
    
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 獲取看板描述
        board_desc = soup.find('div', class_='board-info-detail')
        if board_desc:
            desc_text = board_desc.get_text(strip=True)
            print(f"看板描述: {desc_text}")
        
        # 獲取最新頁數
        latest_page = get_latest_index_improved(board_name)
        print(f"最新頁數: {latest_page}")
        
        # 獲取最新幾篇文章標題
        articles = extract_article_links(board_name, latest_page, session)
        if articles:
            print(f"\n最新 {min(5, len(articles))} 篇文章:")
            for i, article in enumerate(articles[:5], 1):
                print(f"{i}. {article['title']} - {article['author']}")
        
    except Exception as e:
        print(f"獲取看板信息時發生錯誤：{e}")

def export_to_csv(json_file_path):
    """將 JSON 文件轉換為 CSV 格式"""
    try:
        import pandas as pd
        
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        articles = data.get('articles', [])
        if not articles:
            print("JSON 文件中沒有文章數據")
            return
        
        # 準備 DataFrame 數據
        csv_data = []
        for article in articles:
            csv_data.append({
                'board': article.get('board', ''),
                'article_id': article.get('article_id', ''),
                'title': article.get('article_title', ''),
                'author': article.get('author', ''),
                'date': article.get('date', ''),
                'content': article.get('content', ''),
                'ip': article.get('ip', ''),
                'push_count': article.get('message_count', {}).get('push', 0),
                'boo_count': article.get('message_count', {}).get('boo', 0),
                'total_messages': article.get('message_count', {}).get('all', 0)
            })
        
        # 創建 DataFrame 並保存
        df = pd.DataFrame(csv_data)
        csv_file = json_file_path.replace('.json', '.csv')
        df.to_csv(csv_file, index=False, encoding='utf-8-sig')
        print(f"CSV 文件已保存至: {csv_file}")
        
    except ImportError:
        print("需要安裝 pandas 才能導出 CSV: pip install pandas")
    except Exception as e:
        print(f"導出 CSV 時發生錯誤：{e}")

def search_articles_by_keyword(board_name, keyword, max_pages=5):
    """在指定看板中搜尋包含關鍵字的文章"""
    session = get_session()
    found_articles = []
    
    latest_page = get_latest_index_improved(board_name)
    start_page = max(1, latest_page - max_pages + 1)
    
    print(f"在 {board_name} 看板的第 {start_page} 到 {latest_page} 頁搜尋關鍵字: {keyword}")
    
    for page in range(start_page, latest_page + 1):
        print(f"搜尋第 {page} 頁...")
        articles = extract_article_links(board_name, page, session)
        
        for article in articles:
            if keyword.lower() in article['title'].lower():
                found_articles.append(article)
                print(f"找到: {article['title']} - {article['author']}")
        
        time.sleep(0.3)  # 避免請求過於頻繁
    
    print(f"\n搜尋完成，共找到 {len(found_articles)} 篇相關文章")
    return found_articles

def show_articles_from_page(board_name, page_num):
    """顯示指定頁面的文章ID和標題"""
    session = get_session()
    articles = extract_article_links(board_name, page_num, session)
    
    if articles:
        print(f"\n{board_name} 看板第 {page_num} 頁的文章:")
        print("-" * 80)
        for i, article in enumerate(articles, 1):
            print(f"{i:2d}. ID: {article['article_id']}")
            print(f"    標題: {article['title']}")
            print(f"    作者: {article['author']} | 日期: {article['date']}")
            print("-" * 80)
    else:
        print(f"無法獲取第 {page_num} 頁的文章列表")

def main_menu():
    """主選單"""
    print("\n=== PTT 爬蟲工具 ===")
    print("1. 查看看板最新頁數和文章ID")
    print("2. 爬取指定頁面範圍")
    print("3. 爬取單篇文章")
    print("4. 顯示看板信息")
    print("5. 導出文章為 CSV")
    print("6. 關鍵字搜尋文章")
    print("7. 顯示指定頁面的文章ID和標題")
    print("8. 退出")
    
    choice = input("請選擇功能 (1-8): ").strip()
    
    if choice == '1':
        board_name = input("請輸入看板名稱: ").strip()
        latest_index = get_latest_index(board_name)
        if latest_index > 0:
            print(f"目前 {board_name} 的最新頁數為：index{latest_index}.html")
            print("\n最新頁面的文章ID:")
            show_articles_from_page(board_name, latest_index)
        else:
            print("無法獲取最新頁數")
    
    elif choice == '2':
        board_name = input("請輸入看板名稱: ").strip()
        try:
            start_page = int(input("請輸入起始頁數: "))
            end_page = int(input("請輸入結束頁數: "))
            
            if start_page > end_page:
                print("起始頁數不能大於結束頁數")
                return
            
            crawl_board_pages(board_name, start_page, end_page)
            
        except ValueError:
            print("請輸入有效的數字")
    
    elif choice == '3':
        board_name = input("請輸入看板名稱: ").strip()
        print("注意：請輸入文章ID，不是頁面索引")
        print("文章ID範例: M.1234567890.A.123")
        print("您可以從爬取的頁面中找到文章ID")
        article_id = input("請輸入文章ID: ").strip()
        crawl_single_article(board_name, article_id)
    
    elif choice == '4':
        board_name = input("請輸入看板名稱: ").strip()
        show_board_info(board_name)
    
    elif choice == '5':
        file_path = input("請輸入要導出的 JSON 文件路徑: ").strip()
        export_to_csv(file_path)
    
    elif choice == '6':
        board_name = input("請輸入看板名稱: ").strip()
        keyword = input("請輸入關鍵字: ").strip()
        search_articles_by_keyword(board_name, keyword)
    
    elif choice == '7':
        board_name = input("請輸入看板名稱: ").strip()
        try:
            page_num = int(input("請輸入頁碼: "))
            show_articles_from_page(board_name, page_num)
        except ValueError:
            print("請輸入有效的頁碼")
    
    elif choice == '8':
        print("謝謝使用！")
        return False
    
    else:
        print("無效的選擇，請重新輸入")
    
    return True

# 主程式執行
if __name__ == "__main__":
    while True:
        if not main_menu():
            break
