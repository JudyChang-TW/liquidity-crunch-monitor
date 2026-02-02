# Act 設置總結

## 📦 已添加的文件

### 配置文件
- **`.actrc`** - Act 配置文件（使用 GitHub 官方 runner image，啟用 verbose 和 reuse）
- **`.env.local`** - 本地環境變量（不會被提交到 Git）
- **`.github/workflows/event.json`** - 自定義 GitHub event payload（進階用法）

### 腳本
- **`setup_act.sh`** - 一鍵安裝和設置 act
- **`Makefile`** - 簡化常用命令的快捷方式

### 文檔
- **`QUICK_START_ACT.md`** - 5 分鐘快速上手指南
- **`ACT_GUIDE.md`** - 詳細使用指南和進階技巧
- **`CI_TROUBLESHOOTING.md`** - CI 問題診斷和解決方案

### 更新的文件
- **`README.md`** - 添加了 act 使用說明
- **`CONTRIBUTING.md`** - 更新了測試流程，包含 act 驗證
- **`.gitignore`** - 添加了 act 相關的忽略規則

## 🚀 快速開始

### 1. 安裝 act（只需一次）
```bash
./setup_act.sh
```

### 2. 使用 Makefile 快捷命令
```bash
# 查看所有可用命令
make help

# 推送前完整檢查
make quick-check

# 單獨運行 CI jobs
make act-test        # 運行測試
make act-lint        # 運行 linting
make act-type-check  # 運行 type checking
make act-all         # 運行完整 CI pipeline
```

### 3. 開發工作流程
```bash
# 1. 修改代碼
vim src/liquidity_monitor/core/orderbook.py

# 2. 本地快速測試
pytest tests/unit/test_orderbook.py -v

# 3. 完整檢查（推薦）
make quick-check     # pre-commit + tests + act

# 4. 推送
git push origin main
```

## 📚 文檔導航

### 新手入門
1. 📖 **[QUICK_START_ACT.md](../QUICK_START_ACT.md)** - 從這裡開始！
2. 📖 **[ACT_GUIDE.md](../ACT_GUIDE.md)** - 詳細指南

### 遇到問題？
1. 📖 **[CI_TROUBLESHOOTING.md](../CI_TROUBLESHOOTING.md)** - 常見問題和解決方案
2. 📖 **[TESTING_STRATEGY.md](../TESTING_STRATEGY.md)** - 測試策略
3. 📖 **[COVERAGE_REPORT.md](../COVERAGE_REPORT.md)** - Coverage 報告

### 開發指南
1. 📖 **[README.md](../README.md)** - 專案概述
2. 📖 **[CONTRIBUTING.md](../CONTRIBUTING.md)** - 貢獻指南

## ⚡ Makefile 命令快速參考

### 測試相關
```bash
make test           # 本地測試
make test-unit      # 只運行單元測試
make lint           # 運行 linting
make format         # 格式化代碼
make check          # 完整本地檢查
```

### Act 相關
```bash
make act-setup      # 安裝和設置 act
make act-list       # 列出所有 workflows
make act-test       # 運行 CI 測試
make act-lint       # 運行 CI linting
make act-all        # 運行完整 CI
make act-dry        # Dry-run 模式
make act-shell      # 進入 container shell
```

### 工作流程
```bash
make quick-check    # 快速檢查（推薦）
make ci-check       # 完整 CI 檢查
make clean          # 清理臨時文件
make info           # 顯示專案資訊
make dev-status     # 檢查開發環境
```

## 🎯 推薦工作流程

### 日常開發
```bash
# 修改代碼後
make check          # 本地檢查
```

### 推送前驗證
```bash
# 完整驗證（推薦）
make quick-check    # pre-commit + tests + act
```

### 調試 CI 失敗
```bash
# 1. 重現失敗
make act-test

# 2. 詳細輸出
act -j test --verbose

# 3. 交互式調試
make act-shell
```

## 💡 提示

### 首次使用
- ✅ 首次運行 `./setup_act.sh` 會下載 ~2GB Docker image
- ✅ 之後運行會很快（~45 秒）
- ✅ Docker Desktop 必須運行

### 效能優化
- 使用 `make act-test` 而不是 `make act-all` 來快速測試
- `.actrc` 已配置 `--reuse` 來重用 containers
- 多次運行會利用 Docker layer cache

### 常見問題
1. **Docker daemon 錯誤**: `open -a Docker`
2. **權限問題**: 執行 `./setup_act.sh` 中的權限修復步驟
3. **首次運行慢**: 正常，正在下載 Docker image

## 📊 時間對比

| 檢查方式 | 時間 | 優點 | 缺點 |
|---------|------|------|------|
| `pytest` 本地 | 10s | 極快 | 不測試 CI 環境 |
| `pre-commit` | 15s | 快速格式檢查 | 不運行測試 |
| **`make quick-check`** | **60s** | **完整檢查** | **需要 Docker** |
| GitHub CI | 2-4min | 真實 CI | 需要 push |
| 多次 push 調試 | 20-40min | N/A | 浪費時間 |

**結論**: `make quick-check` 是推送前的最佳選擇！

## 🔗 相關連結

- [nektos/act GitHub](https://github.com/nektos/act)
- [GitHub Actions 文檔](https://docs.github.com/en/actions)
- [Docker Desktop](https://www.docker.com/products/docker-desktop)

## ✨ 主要優勢

使用 act 後：
- ✅ **95% 更快的 CI 調試**（45s vs 2-4min）
- ✅ **推送前就知道 CI 結果**
- ✅ **離線開發友好**
- ✅ **節省 GitHub Actions 配額**
- ✅ **完全相同的 CI 環境**

## 需要幫助？

1. 先看 [QUICK_START_ACT.md](../QUICK_START_ACT.md)
2. 遇到問題查 [CI_TROUBLESHOOTING.md](../CI_TROUBLESHOOTING.md)
3. 進階用法看 [ACT_GUIDE.md](../ACT_GUIDE.md)
4. 還是不行？在 GitHub Issues 提問

---

**Happy coding with act! 🚀**
