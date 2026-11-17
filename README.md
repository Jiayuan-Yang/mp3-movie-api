# MP3 Movie API — Parts 1 & 2

本应用使用 FastAPI 提供电影 CSV 上传、检索、搜索和数据清理接口。`src/models.py` 定义请求与响应模型，`src/utils.py` 负责 CSV 检查与日志配置。`src/database.py` 创建 SQLite 表，`src/storage.py` 使用 SQL 完成替换、查询、排序与计数。每次成功上传都会在一个事务中替换当前电影集合，数据库保存于 `data/movies.db`，重启后仍然保留。`data_pipeline/` 复用 MP1 的验证、去重、缺失值和异常值处理模块。`src/cache.py` 使用独立的 FakeRedis，按 limit 缓存完整的 `GET /movies` 响应 90 秒，命中时跳过数据库读取。成功上传或处理保存后会立即清除所有 limit 的缓存，失败操作保留原缓存，搜索接口不使用缓存。`src/middleware.py` 记录请求 ID、耗时和错误，数据库及生成缓存均不提交到 Git。

## 安装和运行

在仓库根目录执行（Python 3.10+，已在 Python 3.12 验证）：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --reload
```

Swagger 文档路径为 `/docs`。默认端口为 8000。可用 `MOVIE_DB_PATH` 环境变量指定其他 SQLite 文件路径；相对路径基于启动工作目录。重启应用不会清空数据库。

## 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 返回 `{"status":"ok","version":"1.0.0"}` |
| POST | `/upload` | multipart 文件字段 `file`；只接受 UTF-8 CSV |
| GET | `/movies?limit=2` | 按 id 返回电影及完整集合总数 |
| GET | `/movies/search?min_rating=8.5&limit=2` | 默认仅返回 id、title；按 rating 降序、id 升序 |
| POST | `/movies/process` | 按 JSON 配置验证并清理集合，原子保存结果 |

```bash
curl -F 'file=@fixtures/sample_movies.csv' http://127.0.0.1:8000/upload
curl 'http://127.0.0.1:8000/movies?limit=2'
curl 'http://127.0.0.1:8000/movies/search?columns=title&columns=rating&min_rating=8.5&limit=2'
curl -X POST http://127.0.0.1:8000/movies/process -H 'Content-Type: application/json' -d '{}'
```

上传要求恰好包含 `title,release_year,rating,genre` 四列（顺序可不同）以及至少一行数据。上传阶段不清理数据；缺失字段保存为 SQL NULL。样例上传为 20 行，重复上传仍为 20 行，搜索返回 Movie C（id 4）及 Movie B（id 2）。查询中的 `columns` 使用重复参数，而不是逗号分隔。

## 处理配置（复用 MP1 / MP2）

`data_pipeline/` 保留仓库原有处理模块，已核对与附件 MP1 的 `src/` 模块一致。`ProcessConfig` 保持 MP2 的嵌套结构、默认值和清理报告格式。日志继续使用 MP2 的请求 ID、请求耗时和通用 500 响应。

发送 `{}` 使用默认配置：去重、删除含缺失值的行，不启用数值验证或异常值清理。完整示例：

```json
{
  "validation": {
    "required_columns": ["title", "release_year", "rating", "genre"],
    "numeric_columns": ["release_year", "rating"]
  },
  "processing": {
    "remove_duplicates": true,
    "missing": {"enabled": true, "axis": "rows"},
    "outliers": {
      "enabled": true,
      "columns": ["rating"],
      "method": "iqr",
      "threshold": 1.5
    }
  }
}
```

数值验证删除无法转换为数字的行；不额外限制年份或评分范围。异常值处理支持 `iqr` 和 `zscore`，启用后使用配置中的列与阈值。默认处理样例删除两条重复行，留下 18 行；启用 rating 异常值处理（上述两种方法，threshold=1.5）后留下 16 行。

上述完整请求处理样例返回：

```json
{
  "validation_rows_removed": 0,
  "cleaning_report": {
    "rows_before": 20, "rows_after": 16, "rows_removed": 4,
    "columns_before": 4, "columns_after": 4, "columns_removed": 0
  }
}
```

空集合处理返回 400。缺少配置要求的列、非法清理 axis 或 method 返回 400，原集合保持不变。配置结构错误返回 422。处理后重新保存，id 会重新分配。

MP2 的 `missing.axis="columns"` 允许删除含缺失值的列；MP3 的 SQL 表固定保留四个电影字段。因此处理报告保留实际删列数，保存时将被删除的字段补为 SQL NULL。推荐使用默认 `axis="rows"`。

## 验证

```bash
.venv/bin/python -m pytest tests -v
```

测试使用隔离的临时数据库，覆盖上传、替换、持久化、NULL、SQL 排序/投影、参数校验、错误上传后的健康检查、清理及事务回滚。按作业要求手动重启 Uvicorn 后再次调用 `/movies`，确认仍能取得上传数据。

缓存日志在 DEBUG 级别显示 HIT、MISS 和失效；重复相同 limit 的查询可观察命中，不同 limit 使用独立键。测试额外验证缓存命中跳过 SQL、写入失效、失败保存保留缓存和 90 秒 TTL。
