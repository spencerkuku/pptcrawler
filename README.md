# PTT 爬蟲工具 - 重新設計版

## 功能特色

### 全新特性
- **類別導向設計**: 更好的代碼結構和可維護性
- **進度條顯示**: 實時顯示爬取進度
- **並發爬取**: 多線程提高爬取效率
- **配置文件支持**: YAML 格式的配置管理
- **命令行界面**: 支持腳本化和交互式使用
- **自動重試機制**: 網絡錯誤自動重試
- **數據驗證**: 確保數據完整性
- **日誌記錄**: 詳細的操作日誌

### 支持的功能
1. **看板預覽**: 查看最新頁數和文章列表
2. **批量爬取**: 指定頁面範圍進行爬取
3. **單篇爬取**: 精確爬取指定文章
4. **關鍵字搜尋**: 在看板中搜尋特定關鍵字
5. **格式導出**: 支持 JSON 和 CSV 格式
6. **配置管理**: 靈活的參數配置

## 安裝依賴

```bash
pip install -r requirements.txt
```

## 使用方法

### 交互式模式
```bash
python ptt_crawler.py
```

### 命令行模式
```bash
# 爬取指定頁面範圍
python ptt_crawler.py --board Gossiping --pages 38950-38952

# 爬取單篇文章
python ptt_crawler.py --board Gossiping --article M.1234567890.A.123

# 搜尋關鍵字
python ptt_crawler.py --board Gossiping --search "關鍵字"

# 使用自定義配置
python ptt_crawler.py --config config.yaml --output ./my_data
```

## 配置選項

編輯 `config.yaml` 文件來自定義設定：

```yaml
delay_between_requests: 0.1  # 請求間延遲
delay_between_pages: 0.5     # 頁面間延遲
timeout: 10                  # 請求超時
max_retries: 3               # 重試次數
max_workers: 4               # 並發數
output_dir: "./crawled_data" # 輸出目錄
```

## 輸出格式

### JSON 格式
```json
{
  "articles": [
    {
      "board": "Gossiping",
      "article_id": "M.1234567890.A.123",
      "title": "文章標題",
      "author": "作者",
      "date": "7/14",
      "content": "文章內容...",
      "url": "https://www.ptt.cc/bbs/Gossiping/M.1234567890.A.123.html",
      "ip": "1.2.3.4",
      "push_count": 10,
      "boo_count": 2,
      "neutral_count": 3,
      "total_messages": 15,
      "messages": [...],
      "crawl_time": "2025-07-14T14:30:00"
    }
  ],
  "crawl_time": "2025-07-14T14:30:00",
  "total_articles": 1,
  "config": {...}
}
```

### CSV 格式
包含所有主要欄位，適合數據分析使用。

## 進階使用

### 自定義配置
```python
from ptt_crawler import PTTCrawler, CrawlConfig

# 創建自定義配置
config = CrawlConfig(
    delay_between_requests=0.2,
    max_workers=2,
    output_dir="./my_output"
)

# 使用配置創建爬蟲
crawler = PTTCrawler(config)

# 爬取文章
articles = crawler.crawl_pages_range("Gossiping", 38950, 38952)
```

### 搜尋和篩選
```python
# 搜尋關鍵字
found_articles = crawler.search_articles("Gossiping", "關鍵字", max_pages=10)

# 爬取單篇文章
article = crawler.crawl_single_article("Gossiping", "M.1234567890.A.123")
```

## 注意事項

1. **請遵守 PTT 使用規範**，避免過於頻繁的請求
2. **建議設置適當的延遲**，預設值已經是較為合理的設定
3. **大量爬取時請考慮網路負載**，可調整並發數
4. **定期更新工具**以應對網站結構變化

## 常見問題

### Q: 爬取失敗怎麼辦？
A: 工具內建重試機制，如果仍然失敗，請檢查網路連線或調整延遲設定。

### Q: 如何提高爬取速度？
A: 可以增加 `max_workers` 參數，但建議不要超過 8，以免對伺服器造成負擔。

### Q: 支援其他看板嗎？
A: 支援所有公開的 PTT 看板。

## 授權

本工具僅供學習研究使用，請遵守相關法律法規和網站使用條款。
