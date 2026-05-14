# Issues

## 现有问题

### Issue 1: jwt_secret_key vs jwt_secret 配置字段名不一致

- **文件**: `backend/src/auth/jwt_handler.py` 和 `backend/src/core/config.py`
- **问题**: `jwt_handler.py` 使用 `settings.jwt_secret`，但 Task Card 测试期望 `settings.jwt_secret_key`
- **影响**: 配置字段命名不一致，但功能正常（JWT 创建和解码都能正常工作）
- **修复建议**: 统一字段名为 `jwt_secret`（已存在）或 `jwt_secret_key`（更明确），保持与 jwt_handler 中的调用一致
- **状态**: ⏳ 待确认命名规范

### Issue 2: JWT 测试需要 JWT_SECRET 环境变量

- **文件**: `backend/src/core/config.py`
- **问题**: `_get_jwt_secret()` 要求 `JWT_SECRET` 必须设置，否则 `create_access_token` 会抛出 `ConfigError`
- **影响**: 在没有 `.env.dev` 或未设置环境变量的环境下，JWT 功能无法测试
- **修复建议**: 
  1. 开发环境提供默认的 JWT_SECRET（仅用于本地开发）
  2. 或在 `configs/.env.example` 中添加 `JWT_SECRET=your_secret_key_here`
- **状态**: ⏳ 待修复

### Issue N: jwt_handler.py 缺少 decode_access_token 函数

- **文件**: `backend/src/auth/jwt_handler.py`
- **问题**: Task Card 要求 `decode_access_token` 函数，但实际代码只有 `verify_token` 和 `decode_token`
- **影响**: 外部调用方无法按预期导入 `decode_access_token`
- **修复建议**: 已添加 `decode_access_token` 函数作为 `verify_token` 的别名 ✅ 已修复
- **状态**: ✅ 已修复（在 c71b688 之后）

---

## 历史 Issues（已修复）

### Issue N: jwt_handler.py 缺少 decode_access_token 函数

- **状态**: ✅ 已修复（在 c71b688 之后）
- **修复**: CC 添加 `decode_access_token` 函数