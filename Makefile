.PHONY: help install test lint format act-setup act-test act-all act-lint clean

# 顏色定義
YELLOW := \033[1;33m
GREEN := \033[0;32m
NC := \033[0m

help: ## 顯示這個幫助訊息
	@echo "$(GREEN)可用的命令：$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-15s$(NC) %s\n", $$1, $$2}'

install: ## 安裝專案依賴
	pip install -e ".[dev]"

test: ## 運行本地測試
	pytest tests/ -v --cov=src/liquidity_monitor --cov-fail-under=70

test-unit: ## 只運行單元測試
	pytest tests/unit/ -v

test-integration: ## 只運行整合測試
	pytest tests/integration/ -v

lint: ## 運行程式碼檢查
	black --check src/ tests/
	isort --check-only src/ tests/
	flake8 src/ tests/
	mypy src/liquidity_monitor

format: ## 格式化程式碼
	black src/ tests/
	isort src/ tests/

pre-commit: ## 運行 pre-commit hooks
	pre-commit run --all-files

# === act 相關命令 ===

act-setup: ## 設置 act（首次使用）
	@echo "$(GREEN)設置 act...$(NC)"
	@chmod +x setup_act.sh
	@./setup_act.sh

act-list: ## 列出所有可運行的 workflows
	@echo "$(GREEN)可用的 GitHub Actions workflows:$(NC)"
	@act -l

act-test: ## 用 act 運行測試 (本地模擬 CI)
	@echo "$(GREEN)運行測試 (模擬 GitHub CI)...$(NC)"
	act -j test

act-lint: ## 用 act 運行 linting (本地模擬 CI)
	@echo "$(GREEN)運行 linting (模擬 GitHub CI)...$(NC)"
	act -j lint

act-type-check: ## 用 act 運行 type checking (本地模擬 CI)
	@echo "$(GREEN)運行 type checking (模擬 GitHub CI)...$(NC)"
	act -j type-check

act-all: ## 用 act 運行完整 CI pipeline
	@echo "$(GREEN)運行完整 CI pipeline (模擬 GitHub CI)...$(NC)"
	act push

act-pr: ## 用 act 模擬 Pull Request CI
	@echo "$(GREEN)運行 PR CI checks (模擬 GitHub CI)...$(NC)"
	act pull_request

act-dry: ## Dry-run: 查看 act 會執行什麼（不實際運行）
	@echo "$(GREEN)Dry-run mode:$(NC)"
	act -n

act-shell: ## 進入 act 的 test container shell (調試用)
	@echo "$(GREEN)進入 test container shell...$(NC)"
	act -j test --shell bash

# === 開發流程快捷命令 ===

check: format lint test ## 運行所有本地檢查（格式化 + linting + 測試）
	@echo "$(GREEN)✅ 所有檢查通過！$(NC)"

ci-check: act-all ## 完整 CI 檢查（推送前驗證）
	@echo "$(GREEN)✅ CI 檢查通過！可以安全推送了$(NC)"

quick-check: ## 快速檢查（pre-commit + 單元測試 + act 測試）
	@echo "$(GREEN)1/3 Running pre-commit...$(NC)"
	@pre-commit run --all-files
	@echo "$(GREEN)2/3 Running unit tests...$(NC)"
	@pytest tests/unit/ -v --tb=short
	@echo "$(GREEN)3/3 Running act CI tests...$(NC)"
	@act -j test -j lint
	@echo "$(GREEN)✅ 快速檢查通過！$(NC)"

# === 清理命令 ===

clean: ## 清理臨時文件和快取
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "$(GREEN)✅ 清理完成$(NC)"

clean-docker: ## 清理 act 使用的 Docker containers 和 images
	@echo "$(YELLOW)清理 act Docker resources...$(NC)"
	docker container prune -f
	docker image prune -f
	@echo "$(GREEN)✅ Docker 清理完成$(NC)"

# === 資訊命令 ===

info: ## 顯示專案資訊
	@echo "$(GREEN)專案資訊:$(NC)"
	@echo "  Python: $(shell python --version)"
	@echo "  Docker: $(shell docker --version 2>/dev/null || echo 'Not installed')"
	@echo "  act: $(shell act --version 2>/dev/null || echo 'Not installed')"
	@echo "  pre-commit: $(shell pre-commit --version 2>/dev/null || echo 'Not installed')"
	@echo ""
	@echo "$(GREEN)Git 狀態:$(NC)"
	@git status --short

dev-status: ## 檢查開發環境狀態
	@echo "$(GREEN)開發環境檢查:$(NC)"
	@echo -n "  Python: "
	@python --version || echo "$(YELLOW)❌ Not found$(NC)"
	@echo -n "  pip: "
	@pip --version | cut -d' ' -f1-2 || echo "$(YELLOW)❌ Not found$(NC)"
	@echo -n "  Docker: "
	@docker --version 2>/dev/null || echo "$(YELLOW)❌ Not installed$(NC)"
	@echo -n "  act: "
	@act --version 2>/dev/null || echo "$(YELLOW)❌ Not installed (run: make act-setup)$(NC)"
	@echo -n "  pre-commit: "
	@pre-commit --version 2>/dev/null || echo "$(YELLOW)❌ Not installed$(NC)"
	@echo -n "  Docker 運行中: "
	@docker ps &>/dev/null && echo "$(GREEN)✅$(NC)" || echo "$(YELLOW)❌ (run: open -a Docker)$(NC)"
