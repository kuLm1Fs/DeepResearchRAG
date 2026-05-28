.PHONY: run install dev

PYTHONPATH := $(shell pwd)/src
export PYTHONPATH

## 安装依赖
install:
	uv sync

dev:
	uv run uvicorn src.api.app:app --reload --app-dir src

## 生产模式启动
prod:
	uv run uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --app-dir src

## 代码检查
lint:
	uv run ruff check src/

## 格式化
format:
	uv run ruff format src/
