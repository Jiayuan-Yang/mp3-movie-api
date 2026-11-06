# MP3 Movie API — Part 1

FastAPI + pandas + SQLite 实现。上传会在一个事务中替换当前电影集合；查询、排序与计数均使用 SQL。数据库自动生成于 `data/movies.db`，不提交到 Git。

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

`data_pipeline/` 完整复用上传的 MP2 模块，已核对与 MP1 的 `src/` 处理模块一致。`ProcessConfig` 保持 MP2 的嵌套结构、默认值和清理报告格式。日志继续使用 MP2 的请求 ID、请求耗时和通用 500 响应。

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
      "enabled": false,
      "columns": ["rating"],
      "method": "iqr",
      "threshold": 1.5
    }
  }
}
```

数值验证删除无法转换为数字的行；不额外限制年份或评分范围。异常值处理支持 `iqr` 和 `zscore`，启用后使用配置中的列与阈值。默认处理样例删除两条重复行，留下 18 行；启用 rating 异常值处理（上述两种方法，threshold=1.5）后留下 16 行。

默认处理样例返回：

```json
{
  "validation_rows_removed": 0,
  "cleaning_report": {
    "rows_before": 20, "rows_after": 18, "rows_removed": 2,
    "columns_before": 4, "columns_after": 4, "columns_removed": 0
  }
}
```

空集合处理返回 400。缺少配置要求的列、非法清理 axis 或 method 返回 400，原集合保持不变。配置结构错误返回 422。处理后重新保存，id 会重新分配。

MP2 的 `missing.axis="columns"` 允许删除含缺失值的列；MP3 的 SQL 表固定保留四个电影字段。因此处理报告保留实际删列数，保存时将被删除的字段补为 SQL NULL。推荐使用默认 `axis="rows"`。

## 验证

```bash
.venv/bin/python -m pytest -q
```

测试使用隔离的临时数据库，覆盖上传、替换、持久化、NULL、SQL 排序/投影、参数校验、错误上传后的健康检查、清理及事务回滚。按作业要求手动重启 Uvicorn 后再次调用 `/movies`，确认仍能取得上传数据。
