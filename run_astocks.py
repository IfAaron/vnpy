from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.ui import MainWindow, create_qapp

from vnpy_portfoliostrategy import PortfolioStrategyApp
from vnpy_datamanager import DataManagerApp


def main():
    """启动 VeighNa Trader（A股回测研究模式，无实盘接口）"""
    qapp = create_qapp()

    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)

    # A股实盘接入时在这里加 Gateway（需要券商账户）
    # from vnpy_xtp import XtpGateway
    # main_engine.add_gateway(XtpGateway)

    main_engine.add_app(DataManagerApp)         # 数据管理：下载/查看历史数据
    main_engine.add_app(PortfolioStrategyApp)   # 组合策略：回测 + 实盘

    main_window = MainWindow(main_engine, event_engine)
    main_window.showMaximized()

    qapp.exec()


if __name__ == "__main__":
    main()
