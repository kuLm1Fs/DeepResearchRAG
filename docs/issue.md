# Issues

## 现有问题

### Issue 1: jwt_secret_key vs jwt_secret 配置字段名不一致

- **文件**: `backend/src/auth/jwt_handler.py` 和 `backend/src/core/config.py`
- **问题**: `jwt_handler.py` 使用 `settings.jwt_secret`，但 Task Card 测试期望 `settings.jwt_secret_key`
- **影响**: 配置字段命名不一致，但功能正常
- **修复建议**: 统一字段名为 `jwt_secret`（已存在）或 `jwt_secret_key`（更明确）
- **状态**: ⏳ 待确认命名规范

### Issue 2: JWT 测试需要 JWT_SECRET 环境变量

- **文件**: `backend/src/core/config.py`
- **问题**: `_get_jwt_secret()` 要求 `JWT_SECRET` 必须设置，否则 `create_access_token` 会抛出 `ConfigError`
- **影响**: 在没有 `.env.dev` 或未设置环境变量的环境下，JWT 功能无法测试
- **修复建议**: 开发环境提供默认 JWT_SECRET（仅用于本地开发）
- **状态**: ⏳ 待修复

---

## 登录功能调试记录（2026-05-14）

### Issue 3: asyncpg 未安装

- **文件**: `backend/pyproject.toml` + 运行环境
- **问题**: `ModuleNotFoundError: No module named 'asyncpg'`
- **原因**: `pyproject.toml` 缺少 asyncpg 依赖
- **修复**: 添加到 `pyproject.toml`：`asyncpg>=0.29.0`
- **状态**: ✅ 已修复（b726e3a 同时添加了 asyncpg + greenlet + sqlalchemy[asyncio]）

### Issue 4: greenlet 未安装

- **文件**: `backend/pyproject.toml`
- **问题**: `No module named 'greenlet'`（SQLAlchemy asyncio 需要）
- **修复**: 添加 `greenlet>=3.0.0` 到依赖
- **状态**: ✅ 已修复

### Issue 5: PostgreSQL 连接地址配置错误

- **文件**: `backend/configs/.env.dev`
- **问题**: 后端从 Mac 连远程 postgres 用的是 `localhost`，但远程只暴露了公网 IP `117.72.164.6`
- **影响**: `ConnectionRefusedError: [Errno 61]`
- **修复**: 本地 Mac 启动后端时指定 `POSTGRES_HOST=117.72.164.6`
- **状态**: ✅ 已修复（但建议远程后端用 `POSTGRES_HOST=localhost` 更安全）

### Issue 6: pg_hba.conf 认证规则顺序错误

- **文件**: 远程服务器 docker postgres 容器内 `pg_hba.conf`
- **问题**: `host all all all md5` 放在前面，远程 TCP 连接都被 md5 拦住
- **影响**: Navicat 和 Python 后端无法通过 TCP 认证（本地 socket 可以）
- **修复**: 删除 `host all all all md5` 这行，或将其移到 trust 规则之后
- **状态**: ✅ 已修复

### Issue 7: models.py 使用 `default=func.now()` 而非 `server_default`

- **文件**: `backend/src/db/models.py`
- **问题**: asyncpg 不接受 SQLAlchemy 的 `func.now()` / `func.current_date` 作为 Python 端的 default 参数
- **现象**: `Neither 'current_date' object nor 'Comparator' object has attribute 'toordinal'`
- **修复**: 所有 `default=func.now()` 改为 `server_default=func.now()`，`default=func.current_date` 改为 `server_default=text("CURRENT_DATE")`
- **状态**: ✅ 已修复（commit b726e3a）

### Issue 8: bcrypt 无法哈希 JWT refresh_token（72字节限制）

- **文件**: `backend/src/api/auth.py`
- **问题**: bcrypt 有 72 字节限制，JWT refresh_token 字符串几百字节
- **现象**: `ValueError: password cannot be longer than 72 bytes`
- **修复**: refresh_token 改用 SHA256 哈希（JWT 本身已签名，只需防泄露）
- **状态**: ✅ 已修复（commit 03c3241）

### Issue 9: timezone-aware 和 timezone-naive datetime 混用

- **文件**: `backend/src/api/auth.py`
- **问题**: 数据库字段是 TIMESTAMP WITHOUT TIME ZONE，但代码用 `datetime.now(timezone.utc)`
- **现象**: `can't subtract offset-naive and offset-aware datetimes`
- **修复**: 统一用 `datetime.utcnow()` 替代 `datetime.now(timezone.utc)`
- **状态**: ✅ 已修复（commit 0874694）

---

## 历史 Issues（已修复）

### Issue N: jwt_handler.py 缺少 decode_access_token 函数

- **状态**: ✅ 已修复（在 c71b688 之后）
- **修复**: CC 添加 `decode_access_token` 函数
