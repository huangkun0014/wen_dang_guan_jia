# -*- coding: utf-8 -*-
# ============================================
# 应用工厂：创建 Flask 应用、注册全部蓝图、初始化数据库
# ============================================

import os
from flask import Flask, send_from_directory

# MCP HTTP 入口只启动一次（应用工厂可能被测试重复调用）
_MCP_HTTP_YI_QI_DONG = False


def _qi_dong_mcp_http():
    """随主服务启动 MCP 的 HTTP 入口（Kimi Work 等插件用 URL 接入）。

    地址: http://127.0.0.1:<MCP_HTTP_DUAN_KOU>/mcp
    工具逻辑在 mcp_server.py 里，仍然是回调本服务的 /api/ai/*，与网页端同一套检索。
    """
    global _MCP_HTTP_YI_QI_DONG
    import config
    if _MCP_HTTP_YI_QI_DONG or not getattr(config, "MCP_HTTP_KAI_QI", False):
        return
    _MCP_HTTP_YI_QI_DONG = True
    try:
        import asyncio
        import threading
        import mcp_server

        def pao():
            try:
                asyncio.run(mcp_server.mcp.run_streamable_http_async(
                    host="127.0.0.1", port=config.MCP_HTTP_DUAN_KOU,
                    streamable_http_path="/mcp"))
            except Exception as e:
                print(f"[MCP] HTTP 服务退出: {e}")

        threading.Thread(target=pao, daemon=True).start()
        print(f"[MCP] HTTP 接口已启动: http://127.0.0.1:{config.MCP_HTTP_DUAN_KOU}/mcp")
    except Exception as e:
        print(f"[MCP] HTTP 入口启动失败（不影响主服务）: {e}")


def chuang_jian_ying_yong():
    app = Flask(__name__, static_folder="static", static_url_path="/static")

    # 初始化数据库（建表，已存在则跳过）
    from app.moxing import chu_shi_hua_shu_ju_ku
    chu_shi_hua_shu_ju_ku()

    # 注册八个子蓝图：搜索 / 收件箱 / 索引 / 系统 / 文件管理 / 浏览 / 体检 / AI 接入
    from app.lan_tu.sousuo.views import sousuo_bp
    from app.lan_tu.shou_jian_xiang.views import shou_jian_xiang_bp
    from app.lan_tu.suo_yin.views import suo_yin_bp
    from app.lan_tu.xi_tong.views import xi_tong_bp
    from app.lan_tu.wen_jian_guan_li.views import wen_jian_bp
    from app.lan_tu.liu_lan.views import liu_lan_bp
    from app.lan_tu.ti_jian.views import ti_jian_bp
    from app.lan_tu.ai_jie_kou.views import ai_jie_kou_bp
    app.register_blueprint(sousuo_bp)
    app.register_blueprint(shou_jian_xiang_bp)
    app.register_blueprint(suo_yin_bp)
    app.register_blueprint(xi_tong_bp)
    app.register_blueprint(wen_jian_bp)
    app.register_blueprint(liu_lan_bp)
    app.register_blueprint(ti_jian_bp)
    app.register_blueprint(ai_jie_kou_bp)

    # 首页：单页应用
    @app.route("/")
    def shou_ye():
        return send_from_directory(app.static_folder, "index.html")

    # MCP 的 HTTP 入口（Kimi Work 等插件用 URL 接入，随主服务一起启停）
    _qi_dong_mcp_http()

    return app
