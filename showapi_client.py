import sqlite3, urllib.parse, urllib.request, json, time, os, threading
from typing import Dict, List, Any, Optional

class ShowApiClient:
    """万维易源 药品信息查询 API (1468-4) 客户端
    查询优先本地 SQLite 表，未命中或过期则调用在线 API 并回写结果
    """

    def __init__(self, appkey: str, base: str = "https://route.showapi.com",
                 cache_file: str = None, cache_ttl: int = 0):
        self.appkey = appkey
        self.base = base.rstrip("/")
        self.cache_ttl = cache_ttl
        self._lock = threading.Lock()

        # 从 cache_file 路径推导 .db 路径
        if cache_file:
            d = os.path.dirname(cache_file) or "."
            os.makedirs(d, exist_ok=True)
            self.db_path = os.path.join(d, "medicine_cache.db")
        else:
            self.db_path = None

        self._init_db()

    def _init_db(self) -> None:
        """创建 drug_cache 表（如不存在）"""
        if not self.db_path:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS drug_cache (
                        search_key TEXT NOT NULL,
                        page       INTEGER NOT NULL DEFAULT 1,
                        max_result INTEGER NOT NULL DEFAULT 10,
                        response_json TEXT NOT NULL,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (search_key, page, max_result)
                    )
                """)
                conn.commit()
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS api_usage (
                        date    TEXT NOT NULL,
                        appkey  TEXT NOT NULL,
                        call_count INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (date, appkey)
                    )
                """)
        except Exception as e:
            print(f"[ShowApiClient] DB 初始化失败: {e}", flush=True)

    # ---------- 公开方法 ----------

    def search_drug(self, search_key: str, page: int = 1, max_result: int = 10,
                    use_cache: bool = True) -> Dict[str, Any]:
        """查询药品：本地表优先 → 未命中/过期则调用 API 并回写"""
        if use_cache and self.db_path and self.cache_ttl >= 0:
            cached = self._get_local(search_key, page, max_result)
            if cached is not None:
                return cached

        # 检查当日配额
        remaining = self.get_remaining_quota()
        if remaining <= 0:
            print(f"[ShowApiClient] 配额耗尽：{self.appkey} 今日 50 次已用完，跳过 API", flush=True)
            return {"showapi_res_body": {"ret_code": "-1", "msg": "配额耗尽"}}
        resp = self._real_search(search_key, page, max_result)

        if use_cache and self.db_path:
            self._save_local(search_key, page, max_result, resp)
        # 计入当日配额
        self._increment_usage()

        return resp

    # ---------- 本地 SQLite 操作 ----------

    def _get_local(self, search_key: str, page: int, max_result: int) -> Optional[Dict[str, Any]]:
        """从本地表查询，过期返回 None"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT response_json, updated_at FROM drug_cache WHERE search_key=? AND page=? AND max_result=?",
                    (search_key.strip(), page, max_result)
                ).fetchone()
            if row:
                resp_json, updated_at = row
                if self.cache_ttl == 0 or time.time() - updated_at < self.cache_ttl:
                    return json.loads(resp_json)
        except Exception as e:
            print(f"[ShowApiClient] 本地查询失败: {e}", flush=True)
        return None

    def _save_local(self, search_key: str, page: int, max_result: int, resp: Dict[str, Any]) -> None:
        """将 API 返回写入本地表（INSERT OR REPLACE）"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO drug_cache (search_key, page, max_result, response_json, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (search_key.strip(), page, max_result,
                     json.dumps(resp, ensure_ascii=False),
                     time.time())
                )
                conn.commit()
        except Exception as e:
            print(f"[ShowApiClient] 本地写入失败: {e}", flush=True)

    # ---------- 在线 API ----------

    def _real_search(self, search_key: str, page: int, max_result: int) -> Dict[str, Any]:
        """实际调用 1468-4（appKey 拼 URL，无需签名）"""
        params = {
            "searchKey": search_key,
            "page": str(page),
            "maxResult": str(max_result),
        }
        url = f"{self.base}/1468-4?appKey={self.appkey}"
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    # ---------- 查询 / 管理 ----------

    def count_records(self) -> int:
        """返回本地表中的记录总数"""
        if not self.db_path:
            return 0
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute("SELECT COUNT(*) FROM drug_cache").fetchone()
                return row[0] if row else 0
        except Exception:
            return 0

    def list_keys(self) -> List[str]:
        """返回本地表中所有去重的 search_key"""
        if not self.db_path:
            return []
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute("SELECT DISTINCT search_key FROM drug_cache ORDER BY search_key").fetchall()
                return [r[0] for r in rows]
        except Exception:
            return []

    def clear_all(self) -> None:
        """清空本地表"""
        if not self.db_path:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM drug_cache")
                conn.commit()
        except Exception:
            pass

    # ---------- 解析 ----------

    # ---------- 配额管理 ----------

    DAILY_LIMIT = 50

    def _increment_usage(self) -> None:
        """将当日调用计数 +1"""
        if not self.db_path:
            return
        today = time.strftime("%Y-%m-%d")
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """INSERT INTO api_usage (date, appkey, call_count)
                       VALUES (?, ?, 1)
                       ON CONFLICT(date, appkey) DO UPDATE SET call_count = call_count + 1""",
                    (today, self.appkey)
                )
                conn.commit()
        except Exception as e:
            print(f"[ShowApiClient] 计数失败: {e}", flush=True)

    def get_daily_usage(self, appkey: str = None) -> int:
        """返回指定 appkey 今日已调用次数"""
        if not self.db_path:
            return 0
        today = time.strftime("%Y-%m-%d")
        ak = appkey or self.appkey
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT call_count FROM api_usage WHERE date=? AND appkey=?", (today, ak)
                ).fetchone()
                return row[0] if row else 0
        except Exception:
            return 0

    def get_remaining_quota(self, appkey: str = None) -> int:
        """返回今日剩余可用次数"""
        used = self.get_daily_usage(appkey)
        return max(0, self.DAILY_LIMIT - used)

    @staticmethod
    def parse_response(resp: Dict[str, Any]) -> List[Dict[str, str]]:
        body = resp.get("showapi_res_body", {})
        if body.get("ret_code") != "0":
            return []
        drugs = body.get("drugList", [])
        out = []
        for d in drugs:
            out.append({
                "药品名称": d.get("drugName") or d.get("tymc") or "",
                "通用名称": d.get("tymc") or "",
                "商品名称": d.get("spmc") or "",
                "生产企业": d.get("manu") or "",
                "批准文号": d.get("pzwh") or "",
                "规格": d.get("gg") or "",
                "剂型": d.get("jx") or "",
                "适应症": d.get("syz") or "",
                "禁忌": d.get("jj") or "",
                "注意事项": d.get("zysx") or "",
                "有效期": d.get("yxq") or "",
                "执行标准": d.get("zxbz") or "",
                "分类": d.get("fl") or "",
                "品牌": d.get("pp") or "",
                "药物过量": d.get("ywgl") or "",
                "孕妇用药": d.get("yfyy") or "",
                "儿童用药": d.get("etyy") or "",
                "老人用药": d.get("lryy") or "",
                "药物相互作用": d.get("ywxhzy") or "",
                "贮藏": d.get("zc") or "",
                "_raw": d,
            })
        return out
