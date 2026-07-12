import urllib.parse, urllib.request, json, time, hashlib, os, threading
from typing import Dict, List, Any

class ShowApiClient:
    """万维易源 药品信息查询 API (1468-4) 客户端，带本地缓存"""

    def __init__(self, appkey: str, secret: str, base: str = "https://route.showapi.com",
                 cache_file: str = None, cache_ttl: int = 30 * 24 * 3600):
        self.appkey = appkey
        self.secret = secret
        self.base = base.rstrip("/")
        self.cache_file = cache_file
        self.cache_ttl = cache_ttl
        self._lock = threading.Lock()
        self._cache = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        if self.cache_file and os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_cache(self) -> None:
        if not self.cache_file:
            return
        try:
            d = os.path.dirname(self.cache_file) or "."
            os.makedirs(d, exist_ok=True)
            tmp = self.cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.cache_file)
        except Exception:
            pass

    def _cache_key(self, search_key: str, page: int, max_result: int) -> str:
        return "##".join([search_key.strip(), str(page), str(max_result)])

    def search_drug(self, search_key: str, page: int = 1, max_result: int = 10,
                    use_cache: bool = True) -> Dict[str, Any]:
        """查询药品；命中本地缓存则直接返回，否则调用 API 并写入缓存"""
        key = self._cache_key(search_key, page, max_result)
        if use_cache and self.cache_file and self.cache_ttl >= 0:
            with self._lock:
                entry = self._cache.get(key)
                if entry and (self.cache_ttl == 0 or time.time() - entry.get("ts", 0) < self.cache_ttl):
                    return entry["resp"]
        resp = self._real_search(search_key, page, max_result)
        if use_cache and self.cache_file:
            with self._lock:
                self._cache[key] = {"ts": time.time(), "resp": resp}
                self._save_cache()
        return resp

    def _real_search(self, search_key: str, page: int, max_result: int) -> Dict[str, Any]:
        """实际调用 1468-4（无缓存）"""
        timestamp = str(int(time.time() * 1000))
        params = {
            "showapi_appid": self.appkey,
            "searchKey": search_key,
            "page": str(page),
            "maxResult": str(max_result),
            "timestamp": timestamp,
        }
        params["showapi_sign"] = self._sign(params)
        url = f"{self.base}/1468-4"
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    def _sign(self, params: Dict[str, str]) -> str:
        """签名：参数按 key 排序拼接 key+value + secret 做 md5"""
        sign_str = "".join(f"{k}{params[k]}" for k in sorted(params)) + self.secret
        return hashlib.md5(sign_str.encode()).hexdigest()

    @staticmethod
    def parse_response(resp: Dict[str, Any]) -> List[Dict[str, str]]:
        """解析返回，提取药品列表"""
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
