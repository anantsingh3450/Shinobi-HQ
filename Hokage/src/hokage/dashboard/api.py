"""REST API endpoints for Hokage Dashboard.

Exposes portfolio data via JSON endpoints suitable for web frontend consumption.
Built on Flask, backed by DashboardService (read-only).
"""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Flask, jsonify
from werkzeug.exceptions import HTTPException

from bots.execution.store.json_trade_store import JsonTradeStore
from bots.portfolio.store import JsonPortfolioStore
from hokage.dashboard.service import DashboardService


def create_dashboard_api(
    portfolio_dir: Path = Path("data/portfolio"),
    trades_dir: Path = Path("data/paper_trades"),
) -> Flask:
    """Create and configure the Flask app for the Hokage Dashboard API.

    Args:
        portfolio_dir: Path to portfolio storage directory.
        trades_dir: Path to trades storage directory.

    Returns:
        Configured Flask application.
    """
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Initialize stores and service
    portfolio_store = JsonPortfolioStore(portfolio_dir)
    trade_store = JsonTradeStore(trades_dir)
    dashboard_service = DashboardService(portfolio_store, trade_store)

    # =====================================================================
    # Blueprint for dashboard routes
    # =====================================================================
    dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/v1")

    # =====================================================================
    # Portfolio Overview
    # =====================================================================
    @dashboard_bp.route("/portfolio/<account_id>/overview", methods=["GET"])
    def portfolio_overview(account_id: str) -> dict:
        """Get high-level portfolio summary.

        Args:
            account_id: Account identifier (e.g., 'paper').

        Returns:
            JSON with portfolio metrics: equity, cash, positions count, etc.
        """
        try:
            overview = dashboard_service.get_portfolio_overview(account_id)
            return jsonify(overview.to_dict())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # =====================================================================
    # Open Positions
    # =====================================================================
    @dashboard_bp.route("/portfolio/<account_id>/positions/open", methods=["GET"])
    def open_positions(account_id: str) -> dict:
        """Get all currently open positions.

        Args:
            account_id: Account identifier.

        Returns:
            JSON list of open positions with market, direction, PnL, etc.
        """
        try:
            positions = dashboard_service.get_open_positions(account_id)
            return jsonify([pos.to_dict() for pos in positions])
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # =====================================================================
    # All Positions
    # =====================================================================
    @dashboard_bp.route("/portfolio/<account_id>/positions/all", methods=["GET"])
    def all_positions(account_id: str) -> dict:
        """Get all positions (open and closed).

        Args:
            account_id: Account identifier.

        Returns:
            JSON list of all positions.
        """
        try:
            positions = dashboard_service.get_all_positions(account_id)
            return jsonify([pos.to_dict() for pos in positions])
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # =====================================================================
    # Trade History
    # =====================================================================
    @dashboard_bp.route("/portfolio/<account_id>/trades", methods=["GET"])
    def trade_history(account_id: str) -> dict:
        """Get trade history, most recent first.

        Query parameters:
            limit: Maximum number of trades to return (default: None = all)

        Args:
            account_id: Account identifier.

        Returns:
            JSON list of trades with execution details.
        """
        try:
            from flask import request

            limit = request.args.get("limit", type=int, default=None)
            trades = dashboard_service.get_trade_history(account_id, limit=limit)
            return jsonify([trade.to_dict() for trade in trades])
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # =====================================================================
    # Account Metrics
    # =====================================================================
    @dashboard_bp.route("/portfolio/<account_id>/metrics", methods=["GET"])
    def account_metrics(account_id: str) -> dict:
        """Get detailed performance metrics.

        Args:
            account_id: Account identifier.

        Returns:
            JSON with return %, PnL, margin usage, etc.
        """
        try:
            metrics = dashboard_service.get_account_metrics(account_id)
            return jsonify(metrics.to_dict())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # =====================================================================
    # Health Check
    # =====================================================================
    @dashboard_bp.route("/health", methods=["GET"])
    def health_check() -> dict:
        """Health check endpoint.

        Returns:
            JSON status.
        """
        return jsonify({"status": "healthy"})

    # Register blueprint
    app.register_blueprint(dashboard_bp)

    # =====================================================================
    # Error handling
    # =====================================================================
    @app.errorhandler(HTTPException)
    def handle_http_error(e: HTTPException) -> dict:
        """Handle HTTP errors."""
        return jsonify({"error": e.description}), e.code

    @app.errorhandler(Exception)
    def handle_error(e: Exception) -> dict:
        """Handle unexpected errors."""
        return jsonify({"error": str(e)}), 500

    return app


def run_dashboard_api(
    host: str = "127.0.0.1",
    port: int = 5000,
    debug: bool = False,
) -> None:
    """Run the dashboard API server.

    Args:
        host: Host to bind to.
        port: Port to bind to.
        debug: Whether to run in debug mode.
    """
    app = create_dashboard_api()
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_dashboard_api(debug=True)
