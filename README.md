# 检验失败组合追因

关联规则的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 参数化分析（异步 Python worker）→ 结果复核（指标、图形、明细、解释、批准）→ 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览和审计轨迹。
三个贯穿全栈的实体：Dataset 数据批次、Job 分析任务、Report 分发计划；辅助 User、Audit、Delivery，以及旧仪器部分项分析专用的 RuleJudgment 逐规则判定登记。

## 旧仪器部分单项数据（legacy）
旧仪器仅留存每批失败项总数 `fail_total` 与部分单项 0/1 结果（未测项留空或 null，至少一项已知）。
- 接入：`POST /api/datasets/legacy`，逐批枚举满足总数的可行补全；已知项与总数对不上（已知失败数超总数、未知项不足以补齐等）整批拒收并注明批次。
- 分析：沿用最多 3 项、正反向独立的候选范围与同一阈值，在所有可行补全空间上把每条规则判为**必然入选 / 可能入选 / 不可能入选**；可能规则各附一份入选与落选的逐批补全见证，供结果页展开核对。判定引擎为纯标准库 Pareto 动态规划（`src/services/uncertain.py`），结果精确而非抽样。
- 中断续跑：逐规则写入 `rule_judgments`（job_id+rule_key 唯一约束），每条独立提交；worker 中断后从已判规则续跑、重试不重复登记，全部判定齐全才置 completed，结果页按 4 秒轮询展示 `judged/total` 进度。
- 数据版本：任务提交时把记录快照与校验和存入 Job（`input_snapshot/input_checksum`），分析沿用提交时版本；补录通过 `POST /api/datasets/{id}/versions` 另存为带谱系（`version_of_id`）的新批次，原批次与在途任务不变，新版本另建任务重算。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18211；后端文档 http://localhost:19211/docs；数据库宿主端口 17711。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、分发、暂停、读取与下载|
|analyst@demo.local|Demo123!|接入、执行、读取与下载；不能批准或安排分发|
|viewer@demo.local|Demo123!|只读与下载|

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；MySQL 8.0；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils}；backend/scripts/seed_demo.py；backend/migrations/initial.py。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer；JobStatus：queued/running/completed/failed。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py；页面按相同角色控制操作入口。

## 环境变量与 Docker
COMPOSE_PROJECT_NAME=assay-rules；FRONTEND_PORT=18211；BACKEND_PORT=19211；DB_PORT=17711；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按 next_run 生成本地收件箱文件。周期 60 秒至 30 天。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1012/，源码不含日志/截图/测试报告。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。
