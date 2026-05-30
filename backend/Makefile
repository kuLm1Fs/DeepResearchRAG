.PHONY: install dev prod lint format docker-build docker-up docker-down

PYTHONPATH := $(shell pwd)/src
export PYTHONPATH

## 安装依赖
install:
	uv sync

## 开发模式（热重载）
dev:
	uv run uvicorn src.api.app:app --reload --app-dir src

## 生产模式（gunicorn 多 worker）
prod:
	uv run gunicorn src.api.app:app -c gunicorn.conf.py

## 代码检查
lint:
	uv run ruff check src/

## 格式化
format:
	uv run ruff format src/

## Docker: 构建所有镜像
docker-build:
	docker compose -f ../docker/docker-compose.yml build

## Docker: 启动全栈（基础设施 + 应用）
docker-up:
	docker compose -f ../docker/docker-compose.yml up -d

## Docker: 停止全栈
docker-down:
	docker compose -f ../docker/docker-compose.yml down
