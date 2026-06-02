# VeighNa 源码学习笔记（A股 + ETF 方向）

> 目标：以 Tech Owner（TO）标准掌握 vnpy 框架，聚焦 A股/ETF 可视化量化交易全链路。
>
> 状态标记：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 已完成

---

## 环境初始化（新机器必做）

```bash
# 1. 安装 uv（如果还没装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. clone 主仓库
git clone https://github.com/vnpy/vnpy
cd vnpy

# 3. 创建虚拟环境并安装（只需做一次）
uv venv --python 3.12
uv pip install -e .

# 4. 按需安装子项目（不需要 clone，直接 pip 安装）
uv pip install vnpy_tushare          # Tushare 数据
uv pip install vnpy_portfoliostrategy # 组合策略+回测
uv pip install vnpy_ctabacktester    # CTA 回测 UI
uv pip install vnpy_datamanager      # 数据管理 UI
```

> Cursor 选解释器：`Cmd+Shift+P` → `Python: Select Interpreter` → 选 `.venv/bin/python`
>
> 如果要深入阅读某个子项目源码，才需要单独 clone 并 `uv pip install -e .`

---

## 数据库配置（PostgreSQL，新机器必做）

vnpy 默认使用 SQLite，推荐切换为 PostgreSQL 16 独立容器。

**第一步：启动 PostgreSQL 容器（OrbStack / Docker）**

```bash
# 注意：用 5433 端口，避免与其他 PostgreSQL 实例冲突
docker run -d \
  --name vnpy-postgres \
  -e POSTGRES_USER=vnpy \
  -e POSTGRES_PASSWORD=vnpy123 \
  -e POSTGRES_DB=vnpy \
  -p 5433:5432 \
  postgres:16

# 验证启动成功
docker ps | grep vnpy-postgres
```

**第二步：安装 Python 驱动**

```bash
uv pip install vnpy_postgresql
uv pip install psycopg2-binary
```

**第三步：创建配置文件**

```bash
mkdir -p ~/.vntrader
cat > ~/.vntrader/vt_setting.json << 'EOF'
{
    "database.name": "postgresql",
    "database.database": "vnpy",
    "database.host": "localhost",
    "database.port": 5433,
    "database.user": "vnpy",
    "database.password": "vnpy123",
    "datafeed.name": "tushare",
    "datafeed.username": "tushare",
    "datafeed.password": "你的tushare_token"
}
EOF
```

> tushare token 在 [tushare.pro](https://tushare.pro) 个人中心获取。`datafeed.username` 填任意非空字符串即可（tushare 只校验非空）。

**第四步：验证连接**

```bash
python -c "from vnpy.trader.database import get_database; db = get_database(); print('连接成功:', db)"
```

输出 `连接成功: <vnpy_postgresql.postgresql_database.PostgresqlDatabase object ...>` 即为成功。

> 容器重启后需要重新 `docker start vnpy-postgres`

---

## 学习路径总览

```
第一阶段 基础设施（事件引擎 + 领域模型）
    ↓
第二阶段 核心引擎（MainEngine + Gateway + 工具层）
    ↓
第三阶段 数据基础设施（数据库 + 数据服务 + 开平转换）
    ↓
第四阶段 可视化界面（UI + K线图表）
    ↓
第五阶段 策略与回测（组合策略 + 脚本策略 + 回测器）
    ↓
第六阶段 A股实盘接入（XTP Gateway）
    ↓
第七阶段 AI投研模块（Alpha 多因子）
```

---

## 第一阶段：基础设施

> 理解整个框架的消息传递基础，所有模块都建立在这之上。
> 预计时间：1-2 天

### 阅读文件

- [X] `vnpy/event/engine.py` — 事件引擎核心

### 学习 Checklist

- [X] 理解 `Event` 数据类：`type` 和 `data` 两个字段的设计意图
- [X] 理解 `EventEngine` 内部：Queue + 独立线程分发 + `_handlers` 字典
- [X] 理解 `_run_timer`：每秒触发 `EVENT_TIMER`，驱动定时任务
- [X] 理解 `register` / `unregister`：handler 的注册与注销生命周期

### 能回答的问题（完成标志）

- [X] 为什么用多线程而非 asyncio？如果换成 asyncio 会有什么问题？
- [X] 如果某个 handler 内部抛出异常，EventEngine 会崩溃吗？
- [X] `EVENT_TIMER` 的实际作用是什么，哪些模块依赖它？

---

## 第一阶段：学习问答记录

### Q1：`if event.type in self._handlers` 是什么语法？

`in` 用于 dict（包括 `defaultdict`）时，检查的是**键是否存在**，不会触发 `defaultdict` 的自动创建副作用。

`defaultdict(list)` 的陷阱：直接访问不存在的键会自动插入一个空 list。如果省略 `if` 直接写 `self._handlers[event.type]`，每次来一个没有 handler 的事件类型都会往字典里插入空 list，导致内存持续增长。

正确模式：**用 `in` 做存在性检查（不触发创建），确认存在后再访问 value**。

---

### Q2：为什么用 Thread 而不用 asyncio？Python 有多线程吗？

Python 有真实的操作系统线程，但有 **GIL（全局解释器锁）**，任意时刻只有一个线程执行 Python 字节码。

GIL 会在以下情况**主动释放**：I/O 等待、系统调用、C 扩展调用（如 CTP 的 C++ 回调）、`sleep()`。

`queue.get(block=True)` 属于阻塞等待，GIL 在此释放，所以 EventEngine 线程等待时，Qt GUI 线程和 Timer 线程都可以正常运行。

**不用 asyncio 的核心原因**：
1. 策略开发者写的 handler 是普通 `def`，无需 `async/await`，学习门槛低
2. asyncio 是协作式调度，handler 不 `await` 就不让出控制权，CPU 密集的策略代码会卡死整个事件循环；多线程是抢占式，GIL 强制切换，更容错
3. Qt GUI 与 asyncio 事件循环集成复杂，与多线程天然兼容

**实际分工**：vnpy 的网络 I/O 层（REST/WebSocket 客户端）用 asyncio，业务事件层用多线程，通过 Queue 桥接。

---

### Q3：Qt 是什么？Qt 主线程是什么？

Qt 是跨平台 C++ GUI 框架，vnpy 通过 `PySide6` 调用它来绘制交易界面的所有窗口、按钮、表格。

Qt 强制要求：**所有 UI 操作必须在主线程执行**。程序启动后 `qapp.exec()` 让主线程进入 Qt 事件循环，专门响应界面事件。

vnpy 的线程结构：
```
Qt 主线程          → 界面渲染，响应鼠标/键盘
EventEngine._thread → 阻塞在 queue.get()，分发事件
EventEngine._timer  → sleep(1)，每秒 put EVENT_TIMER
Gateway 回调线程    → CTP/XTP 的 C++ 回调天然在独立线程
```

跨线程刷新 UI 通过 Qt 的**信号/槽机制**实现，这是 Qt 提供的线程安全通信方式。

---

### Q4：EVENT_TIMER 的作用是什么？

EVENT_TIMER 是系统**心跳**，每秒必然触发一次，与外部行情无关。

用于解决"行情驱动"覆盖不到的场景：
- **断线检测/重连**：行情停了就没有 Tick 事件，只能靠定时器发现连接断开
- **定时查询账户**：主动 query_account / query_position
- **策略时间条件**：如"14:50 强制平仓"，需要定期检查时间而非等行情触发
- **夜盘日终清算**：行情停止后的定期清理

---

### Q5：handler 内部抛异常，EventEngine 会崩溃吗？

**会**。`_process` 内部没有 try/except，`_run` 的 try/except 只捕获 `Empty`（队列超时）。

handler 抛出异常会冒泡导致 `_thread` 线程退出，后续所有事件无法处理，系统**静默失效**（界面还活着，行情和委托不再响应）。

框架的设计取舍：把异常处理责任交给用户，`CtaTemplate` 等策略基类在模板层做了兜底（内部有 try/except 包裹 on_tick 等方法），EventEngine 核心层不做兜底。

策略开发时应在 handler 里自己捕获异常：
```python
def on_tick(self, tick: TickData):
    try:
        ...
    except Exception as e:
        self.write_log(f"on_tick 异常: {e}")
```

---

### 阅读文件

- [X] `vnpy/trader/constant.py` — 所有枚举常量
- [X] `vnpy/trader/object.py` — 所有领域数据类

### 学习 Checklist

- [X] 掌握全部枚举：`Direction`、`Offset`、`Exchange`、`Interval`、`Status`、`Product`、`OrderType`
- [X] 掌握全部数据类：`TickData`、`BarData`、`OrderData`、`TradeData`、`PositionData`、`AccountData`、`ContractData`
- [x] 理解 `vt_symbol` 命名规则：`{symbol}.{exchange}`，如 `000001.SSE`
- [x] 理解 `OrderRequest` vs `OrderData` 的区别：Request 是发出去的意图，Data 是收到的状态

### 能回答的问题（完成标志）

- [X] A股股票的 `Exchange` 应该用哪个值？ETF 呢？
- [X] `Offset.NONE` 在 A 股中为什么比期货更常用？
- [X] `TickData` 的 `bid_price_1` ~ `bid_price_5` 是什么？A股 Level-2 和普通行情的区别在哪？

---

## 第一阶段：constant.py / object.py 问答记录

### Q6：A 股和 ETF 的 Exchange 分别用哪个值？

按代码开头判断：

| 代码开头 | Exchange | 例子 |
|---------|----------|------|
| 6 开头 | `SSE` | `600519.SSE`（茅台）、`601318.SSE`（平安）|
| 0 / 3 开头 | `SZSE` | `000001.SZSE`（平安银行）、`300750.SZSE`（宁德时代）|
| 8 / 4 开头 | `BSE` | 北交所股票 |
| 51 开头（ETF）| `SSE` | `510300.SSE`（沪深300ETF）|
| 15 开头（ETF）| `SZSE` | `159915.SZSE`（创业板ETF）|

`vt_symbol` 拼法：`{代码}.{Exchange}`，如 `600519.SSE`。

---

### Q7：Offset.NONE 在 A 股中为什么比期货更常用？

期货可以做空，持仓有多头和空头之分，委托**必须**区分开仓（`OPEN`）和平仓（`CLOSE`），否则交易所不知道这笔单是建新仓还是了结旧仓。

A 股不能做空，只有买入和卖出，不存在"开仓/平仓"的概念：

| 操作 | Offset | Direction |
|------|--------|-----------|
| 期货开多 | `OPEN` | `LONG` |
| 期货平多 | `CLOSE` | `SHORT` |
| A 股买入 | `NONE` | `LONG` |
| A 股卖出 | `NONE` | `SHORT` |

`Offset.NONE` 表示"这个维度对 A 股不适用"。写 A 股策略时直接 `buy()` / `sell()`，不需要考虑 `Offset`。

---

### Q8：TickData 的 bid_price_1~5 是什么？Level-1 和 Level-2 的区别？

**盘口**是市场上所有挂单的快照，分买盘（bid）和卖盘（ask）：

```
卖5  19.55   ask_price_5 / ask_volume_5
卖1  19.51   ask_price_1 / ask_volume_1  ← 最优卖价
─────────────
     19.50   last_price（最新成交价）
─────────────
买1  19.49   bid_price_1 / bid_volume_1  ← 最优买价
买5  19.45   bid_price_5 / bid_volume_5
```

`bid_price_1` 是买方出价最高的那一档，`ask_price_1` 是卖方要价最低的那一档，两者之差是**买卖价差（spread）**。

| | Level-1（普通，免费）| Level-2（深度，付费）|
|--|------------------|------------------|
| 盘口档位 | 买卖各 5 档 | 买卖各 10 档 |
| 逐笔数据 | 无 | 每一笔成交/委托都推送 |
| 主力追踪 | 无 | 可识别大单方向 |

普通策略只需要 `last_price`、`bid_price_1`、`ask_price_1`，Level-1 够用。高频或日内策略才需要 Level-2。

---

## 第二阶段：核心引擎

> 掌握 MainEngine 的插件化设计，理解委托从发出到成交的完整流程。
> 预计时间：2-3 天

### 阅读文件

- [ ] `vnpy/trader/engine.py` — 主引擎、OMS、日志引擎

### 学习 Checklist

- [ ] 理解 `MainEngine.add_gateway()` / `add_app()` / `add_engine()` 插件注册机制
- [ ] 理解 `OmsEngine`：`ticks` / `orders` / `trades` / `positions` 字典如何维护
- [ ] 理解 `OmsEngine.on_order()`：委托状态变更的完整流程
- [ ] 理解 `LogEngine`：日志如何从各模块汇聚到统一输出
- [ ] 了解 `EmailEngine` / `WechatEngine`：旁路通知体系

### 能回答的问题（完成标志）

- [X] 多个 Gateway 同时连接时，`vt_symbol` 如何区分来源？（`vt_orderid` 的格式）
- [X] `OmsEngine` 的 `on_position()` 在什么时机被调用？
- [X] 如果要新增一个"飞书通知引擎"，需要改哪些文件？

---

## 第二阶段：engine.py 问答记录

### Q9：OmsEngine 的 process_tick_event 只是存了一下，处理逻辑在哪？

`OmsEngine` 的职责是**维护内存状态缓存**，不是做业务逻辑。

```python
def process_tick_event(self, event: Event) -> None:
    tick: TickData = event.data
    self.ticks[tick.vt_symbol] = tick   # 覆盖写入，永远保存最新一条
```

Gateway 推来的 Tick 是一次性事件，分发完就没了。OmsEngine 把它存到字典里，让任意模块随时能查到当前最新价：

```python
tick = self.main_engine.get_tick("600519.SSE")  # 随时可查
```

同理，`orders`、`trades`、`positions`、`accounts` 字典都是同样的模式：收到事件 → 覆盖写入 → 供后续查询。

**业务处理**在策略的 `on_tick` 里，OmsEngine 和策略的 `on_tick` 同时注册到 `EVENT_TICK`，各司其职：OmsEngine 更新缓存，策略执行交易逻辑。

---

### Q10：多个 Gateway 同时连接时，vt_symbol 如何区分来源？vt_ 前缀是什么意思？

`vt_symbol` **不区分** Gateway 来源，同一只股票在任何 Gateway 里都是 `600519.SSE`。

需要区分来源的是委托、成交、持仓、账户，通过 `gateway_name` 前缀拼接成全局唯一 ID：

| 字段 | 格式 | 例子 |
|------|------|------|
| `vt_orderid` | `{gateway_name}.{orderid}` | `XTP.123456` |
| `vt_tradeid` | `{gateway_name}.{tradeid}` | `XTP.789` |
| `vt_positionid` | `{gateway_name}.{vt_symbol}.{direction}` | `XTP.600519.SSE.多` |
| `vt_accountid` | `{gateway_name}.{accountid}` | `XTP.888888` |

`vt_` 前缀是 **VeighNa Trader** 的缩写，代表"经框架拼接、全系统唯一的 ID"，区别于交易所原始返回的 ID。所有数据对象都有 `gateway_name` 字段，这是整个框架的基础约定。

---

### Q11：OmsEngine 的 on_position() 在什么时机被调用？

不是方向变化时触发，而是 Gateway **主动推送**，有两个时机：

1. **连接登录后**：Gateway 查询账户所有持仓，逐条推送 `EVENT_POSITION` 做初始化同步
2. **每笔成交后**：持仓数量变化，Gateway 推送最新的 `PositionData` 快照

`PositionData` 包含：持仓数量 `volume`、冻结数量 `frozen`（已委托卖出但未成交）、持仓均价 `price`、浮动盈亏 `pnl`。

每次收到推送，OmsEngine 用新数据覆盖字典里的旧数据，始终保存最新持仓快照。

---

### Q12：如果要新增"飞书通知引擎"，需要改哪些文件？

只需改 **`vnpy/trader/engine.py`** 一个文件，分三步：

1. 新增 `FeishuEngine` 类，继承 `BaseEngine`，实现 `load_setting()` 和 `send_feishu()`
2. 在 `MainEngine.__init__` 里加一行 `self.add_engine(FeishuEngine)`
3. 在 `MainEngine.send_email()` 方法里调用 `feishu_engine.send_feishu(...)`

配置文件 `feishu_setting.json` 由用户放在 `~/.vntrader/` 目录下，框架的 `load_json()` 工具函数自动从该目录读取，无需处理路径。

这体现了插件化设计的价值：扩展一个通知渠道只改一个文件，改动范围极小。

---

### 阅读文件

- [ ] `vnpy/trader/gateway.py` — Gateway 抽象接口
- [ ] `vnpy/trader/app.py` — App 元数据抽象

### 学习 Checklist

- [ ] 理解 `BaseGateway` 必须实现的 6 个方法：`connect`、`disconnect`、`subscribe`、`send_order`、`cancel_order`、`query_account`
- [ ] 理解 `on_tick` / `on_order` / `on_trade` 的推送约定：把数据推入 EventEngine
- [ ] 理解 `BaseApp` 的 5 个字段：`app_name`、`app_module`、`app_engine`、`widget_name`、`icon_name`

### 能回答的问题（完成标志）

- [X] 为什么 `BaseGateway` 接口设计得如此简单？增加新方法会有什么后果？
- [X] `subscribe()` 方法的 `SubscribeRequest` 包含哪些字段？
- [X] 一个 App 是如何被 MainEngine 加载并显示在菜单栏的？

---

## 第二阶段：gateway.py / app.py 问答记录

### Q13：为什么 BaseGateway 接口设计得如此简单？增加新方法会有什么后果？

原因一（生命周期抽象）：`connect` → `subscribe` → `send_order/cancel_order` → `close` 覆盖了所有 Gateway 共同的操作流程。

原因二（下游生态稳定性，最核心）：`BaseGateway` 是 80+ 个插件包的契约。`MainEngine` 只认识 `BaseGateway`，不认识具体实现类。如果新增一个 `@abstractmethod`，所有实现类都必须跟着改，否则实例化时报错——一个接口改动波及整个生态，升级成本极高。

解决方案：可选能力用**有默认实现的普通方法**而非 `@abstractmethod`：
- `send_quote` / `cancel_quote`：期权做市用，普通 Gateway 的默认实现直接返回空
- `query_history`：历史数据查询，默认返回空列表

规则：**`@abstractmethod` 只用于所有实现类都必须支持的核心能力；可选扩展能力用带默认实现的普通方法。**

---

### Q14：SubscribeRequest 包含哪些字段？

只有两个字段，设计非常克制：

```python
class SubscribeRequest:
    symbol: str        # 股票代码，如 "600519"
    exchange: Exchange # 交易所，如 Exchange.SSE
    # __post_init__ 自动生成：
    vt_symbol: str     # "600519.SSE"
```

订阅行情只需要告诉 Gateway"我要哪只标的"，推送频率和数据类型由 Gateway 内部决定，不暴露给调用方。

---

### Q15：一个 App 是如何被 MainEngine 加载并显示在菜单栏的？

分两个阶段：

**阶段一：注册（`run.py` 里调用 `add_app`）**
```python
main_engine.add_app(CtaStrategyApp)
```
内部：实例化 App 存入 `self.apps` 字典，同时调用 `add_engine(app.engine_class)` 启动对应业务引擎（如 `CtaEngine`）。此时只是记录元数据，UI 无变化。

**阶段二：UI 加载（`MainWindow` 初始化菜单栏）**

遍历所有注册的 App，对每个 App：
1. `import_module(app.app_module + ".ui")` 动态导入 UI 模块
2. `getattr(ui_module, app.widget_name)` 拿到 Widget 类
3. 在"功能"菜单里添加菜单项，点击时打开对应 Widget

`BaseApp` 的 6 个字段各司其职：

| 字段 | 用途 |
|------|------|
| `app_name` | 唯一标识，字典 key |
| `app_module` | 模块路径，用于 `import_module` |
| `display_name` | 菜单栏显示名，如"CTA策略" |
| `engine_class` | 业务引擎类，`add_app` 时自动启动 |
| `widget_name` | UI Widget 的类名 |
| `icon_name` | 菜单图标文件名 |

**延迟导入**：UI 模块在菜单初始化时才 import，不是程序启动时全部加载，某个 App 的 UI 出问题不影响整体启动。

---

### 阅读文件

- [ ] `vnpy/trader/utility.py` — 工具层（BarGenerator、ArrayManager 等）

### 学习 Checklist

- [ ] 深入理解 `BarGenerator`：Tick → 1分钟Bar → N分钟/小时/日Bar 的合成逻辑
- [ ] 理解 `BarGenerator` 的跨日边界处理（夜盘、集合竞价）
- [ ] 理解 `ArrayManager`：固定长度 numpy 环形数组的设计
- [ ] 了解 `ArrayManager` 内置的常用指标：`sma`、`ema`、`macd`、`rsi`、`atr`
- [ ] 了解 `TRADER_DIR`、`get_folder_path`：用户数据的存储路径约定

### 能回答的问题（完成标志）

- [X] `BarGenerator` 合成日线时，A 股的收盘时间（15:00）如何处理？
- [X] `ArrayManager` 为什么用固定长度数组而非 Python list？
- [X] 如果 Tick 数据中断了 30 秒，`BarGenerator` 会怎么处理？

---

## 第二阶段：utility.py 问答记录

### Q16：BarGenerator 合成日线时，A 股的收盘时间（15:00）如何处理？

收盘时间**不是框架内置的**，由用户创建 `BarGenerator` 时通过 `daily_end` 参数传入，不传直接报错：

```python
bg = BarGenerator(
    on_bar=self.on_bar,
    window=1,
    on_window_bar=self.on_daily_bar,
    interval=Interval.DAILY,
    daily_end=time(hour=15, minute=0)   # A 股传 15:00，期货夜盘传 23:00 等
)
```

`update_bar_daily_window` 每次收到分钟 Bar 时检查：

```python
if bar.datetime.time() == self.daily_end:   # 时间戳 == 15:00
    self.on_window_bar(self.daily_bar)       # 推送日线 Bar
    self.daily_bar = None                    # 清空，等待下一天
```

这样设计的好处：不同品种收盘时间不同（A 股 15:00、美股 16:00、期货夜盘 23:00），通过外部传参而非硬编码，同一套代码支持所有品种。

---

### Q17：ArrayManager 为什么用固定长度 numpy 数组而非 Python list？

三个原因：

1. **TA-Lib 接口要求**（最核心）：`ArrayManager` 的核心用途是喂给 TA-Lib 计算指标，TA-Lib 是 C 写的，只接受 `np.ndarray`，不接受 list。用 list 每次都要转换，既慢又浪费内存。

2. **内存可控**：实盘运行几个月会积累大量 Bar，list 无限追加会持续占用内存。计算 MA20 只需要最近 100 条数据，固定长度数组超出后自动丢弃最旧的数据。

3. **计算速度**：numpy 向量运算是 C 实现，比 Python list 循环快 10-100 倍。`np.zeros(100)` 在内存里是一块连续的 float64，TA-Lib 直接用指针操作。

`update_bar` 的滚动逻辑：每来一根新 Bar，整体左移一位（`array[:-1] = array[1:]`），最新值写到末尾（`array[-1] = new_value`），最旧的数据自动被覆盖丢弃。

---

### Q18：如果 Tick 数据中断了 30 秒，BarGenerator 会怎么处理？

`BarGenerator` **感知不到中断**，没有任何中断检测逻辑，完全被动，只有 Tick 进来才工作。

中断期间当前 Bar 静静挂在内存里，等待下一个 Tick。

恢复后的处理取决于中断时长：

- **中断在同一分钟内（< 1 分钟）**：新 Tick 进来，`minute` 没变，直接更新当前 Bar，30 秒空白对 Bar 没有影响
- **中断跨越整分钟**：新 Tick 进来，检测到 `minute` 变了，推送之前的 Bar，开新 Bar，**中间整分钟的 Bar 永远丢失**

```
正常：10:01 Bar → 10:02 Bar → 10:03 Bar
中断：10:01 Bar →（中断）→ 10:03 Bar（10:02 Bar 永远丢失）
```

这是框架的已知缺陷：ArrayManager 会有空缺，依赖连续 Bar 的指标（MA、ATR）结果会有偏差，框架不报错也不提示。实盘中需要自己监控行情连续性。

---

## 第三阶段：数据基础设施

> 理解历史数据的完整链路：下载 → 入库 → 回测加载。
> 预计时间：1-2 天

### 阅读文件

- [ ] `vnpy/trader/database.py` — 数据库抽象接口
- [ ] `vnpy/trader/setting.py` — 全局配置

### 学习 Checklist

- [ ] 理解 `BaseDatabase` 接口：`save_bar_data`、`load_bar_data`、`get_bar_overview`
- [ ] 理解通过 `SETTINGS["database.driver"]` 动态加载数据库实现的机制
- [ ] 理解 `BarOverview`：为什么需要这个元数据索引？
- [ ] 了解 `SETTINGS` 的加载顺序：默认值 → `~/.vntrader/vt_setting.json` 覆盖

### 能回答的问题（完成标志）

- [X] 如何切换使用 SQLite vs MongoDB 作为后端？
- [X] `get_bar_overview()` 返回的数据结构是什么？在 UI 中如何展示？
- [X] `BarOverview` 不存在时，`load_bar_data()` 会发生什么？

---

## 第三阶段：database.py / setting.py 问答记录

### Q19：如何切换使用 SQLite vs MongoDB 作为后端？

修改 `~/.vntrader/vt_setting.json`（不要改源码），只需写要覆盖的字段：

```json
// 切换到 PostgreSQL
{
    "database.name": "postgresql",
    "database.database": "vnpy",
    "database.host": "localhost",
    "database.port": 5433,
    "database.user": "vnpy",
    "database.password": "vnpy123"
}
```

加载机制（`database.py` 关键代码）：

```python
database_name = SETTINGS["database.name"]          # 读配置，如 "postgresql"
module_name = f"vnpy_{database_name}"               # 拼出 "vnpy_postgresql"
module = import_module(module_name)                 # 动态导入
database = module.Database()                        # 实例化
```

如果对应包未安装（`ModuleNotFoundError`），自动降级回 SQLite，不崩溃——这是容错设计。

每种数据库需要单独安装驱动包：
```bash
uv pip install vnpy_postgresql && uv pip install psycopg2-binary
uv pip install vnpy_mongodb
uv pip install vnpy_sqlite    # 默认已有
```

`SETTINGS` 加载顺序：`setting.py` 硬编码默认值 → `~/.vntrader/vt_setting.json` 用 `update()` 覆盖。

`.vntrader` 路径查找：优先当前工作目录下的 `.vntrader`，找不到则用 `~/.vntrader`，不存在时**自动创建**。

---

### Q20：get_bar_overview() 返回的数据结构是什么？在 UI 中如何展示？

```python
@dataclass
class BarOverview:
    symbol: str = ""
    exchange: Exchange | None = None
    interval: Interval | None = None
    count: int = 0        # 数据条数
    start: datetime | None = None
    end: datetime | None = None
```

`BarOverview` 是**元数据索引表**，专为 UI 快速展示而设计。

设计意图：数据库里存了几百只股票几百万条 BarData，如果 UI 要展示"我有哪些数据"，全表扫描需要几十秒。`BarOverview` 单独维护一张每只股票一行的元数据表，UI 查这张表瞬间返回。

`vnpy_datamanager` 里展示为一张表格，每个 `BarOverview` 对象对应一行：

| 代码 | 交易所 | 周期 | 数量 | 开始时间 | 结束时间 |
|------|--------|------|------|---------|---------|
| 600519 | SSE | 日线 | 1200 | 2019-01-02 | 2023-12-29 |

---

### Q21：BarOverview 不存在时，load_bar_data() 会发生什么？

**互不影响**。`load_bar_data` 和 `get_bar_overview` 是独立的两张表的查询，互不依赖。

- `load_bar_data` 直接查 bar 数据表，按条件过滤，数据不存在时返回 `[]`，不报错
- `BarOverview` 缺失只影响 DataManager **UI 的概览展示**，数据本身仍可正常读写

`save_bar_data` 写入时会同时更新两张表，正常情况下不会出现数据有但 Overview 没有的情况。

---

### 阅读文件

- [ ] `vnpy/trader/datafeed.py` — 数据服务抽象接口

### 学习 Checklist

- [ ] 理解 `BaseDatafeed` 接口：`query_bar_history`、`query_tick_history`
- [ ] 理解 `HistoryRequest`：`symbol`、`exchange`、`start`、`end`、`interval` 字段
- [ ] 了解 datafeed 与 database 的职责分工：datafeed 是数据来源，database 是本地存储

### 能回答的问题（完成标志）

- [X] datafeed 和 database 的数据流向是怎样的？谁调用谁？
- [X] 如果 tushare 接口限速，应该在哪里加重试逻辑？

---

## 第三阶段：datafeed.py 问答记录

### Q22：datafeed 和 database 的数据流向是怎样的？谁调用谁？

datafeed 和 database **互不认识**，中间由 `vnpy_datamanager`（或用户脚本）协调：

```
datafeed.query_bar_history(req)   ← 从外部数据源（tushare/xt）拉取数据
    ↓ 返回 list[BarData]
DataManager（协调层）
    ↓
database.save_bar_data(bars)      ← 写入本地数据库
```

**回测时方向相反**，datafeed 完全不参与：

```
回测引擎 → database.load_bar_data() → 只读本地，不联网
```

职责边界：datafeed 负责联网拉数据（有网络依赖），database 负责本地存取（无网络依赖），两者通过上层调用方解耦。

---

### Q23：如果 tushare 接口限速，应该在哪里加重试逻辑？

最优位置是 **`vnpy_tushare` 的 `query_bar_history` 实现里**，不是 DataManager。

原因：限速是 tushare 特有的问题，应该封装在 datafeed 实现层，对上层调用者透明。DataManager 是 UI 层，不应该了解底层数据源的特性，否则换一个 datafeed 还要改 DataManager，违反分层原则。

```python
# vnpy_tushare 里的正确位置（伪代码）
def query_bar_history(self, req):
    for attempt in range(3):
        try:
            df = ts.pro_bar(...)
            return self._parse(df)
        except Exception as e:
            if "限速" in str(e):
                time.sleep(60)   # 等待后重试
                continue
            raise
    return []
```

分层原则：**每一层只处理自己职责范围内的问题，上层对下层的实现细节透明。**

---

### 阅读文件

- [ ] `vnpy/trader/converter.py` — 开平仓转换

### 学习 Checklist

- [ ] 理解 `OffsetConverter` 的作用：国内期货今昨仓规则
- [ ] 理解上期所（SHFE）和其他交易所的开平规则差异
- [ ] **A 股重点**：A 股不需要开平转换，理解为什么 `Offset.NONE` 是 A 股的默认值

### 能回答的问题（完成标志）

- [ ] 在 A 股策略中，是否需要初始化 `OffsetConverter`？为什么？
- [ ] ETF 期权有开平仓，对应的 `Offset` 如何设置？

---

## 第四阶段：可视化界面

> 理解事件驱动 UI 的绑定方式，能看懂和修改界面组件。
> 预计时间：1 天

### 阅读文件

- [ ] `vnpy/trader/ui/mainwindow.py` — 主窗口
- [ ] `vnpy/trader/ui/widget.py` — 通用控件

### 学习 Checklist

- [ ] 理解主窗口的 Dock 注册机制：App 如何将自己的 Widget 注册到主窗口
- [ ] 理解 `BaseMonitor`（表格基类）：如何订阅事件并线程安全地刷新表格
- [ ] 理解 `BaseMonitor` 的 `event_type` 字段：绑定哪种事件自动更新

### 能回答的问题（完成标志）

- [ ] `BaseMonitor` 如何解决 UI 线程安全问题？（Qt 的跨线程信号机制）
- [ ] 如果要新增一个"自选股监控面板"，需要实现哪些基类方法？

---

## 第四阶段：mainwindow.py / widget.py 问答记录

### Q24：BaseMonitor 如何解决 UI 线程安全问题？

核心是两行代码：

```python
self.signal.connect(self.process_event)                           # 第303行
self.event_engine.register(self.event_type, self.signal.emit)    # 第304行
```

EventEngine 线程收到事件时，调用的是 `signal.emit(event)`，这是把事件**发射到 Qt 信号系统**，而不是直接调用 `process_event`。

Qt 的 `Signal` 是跨线程通信机制：当 `signal.emit` 在非主线程被调用时，Qt 内部把这个调用**投递到主线程的事件队列**，等主线程空闲时才执行 `process_event`。

```
EventEngine 线程 → signal.emit(event)  →  Qt 跨线程队列  →  主线程执行 process_event → 刷新表格
```

`signal.emit` 在任何线程调用都安全，Qt 保证 slot（`process_event`）一定在主线程执行。`BaseMonitor` 不需要写任何锁或线程同步代码——**Qt Signal 本身就是线程安全的跨线程调度器**。

---

### Q25：新增"自选股监控面板"需要实现哪些基类方法？

**不需要实现任何方法**，只需声明 4 个类变量：

```python
class WatchlistMonitor(BaseMonitor):
    event_type: str = EVENT_TICK     # 监听哪种事件
    data_key: str = "vt_symbol"      # 行的唯一 key（已有则更新，没有则新增）
    sorting: bool = True             # 是否支持列头排序

    headers: dict = {
        "symbol":     {"display": "代码",   "cell": BaseCell, "update": False},
        "name":       {"display": "名称",   "cell": BaseCell, "update": True},
        "last_price": {"display": "最新价", "cell": BaseCell, "update": True},
        "volume":     {"display": "成交量", "cell": BaseCell, "update": True},
    }
```

`process_event`、`insert_new_row`、`update_old_row`、事件注册、线程同步全部由 `BaseMonitor` 通用实现处理，子类完全不需要重写。

`headers` 每个字段的含义：
- `display`：列头显示名称
- `cell`：渲染类（`BaseCell` 普通文本，`BidCell` 买盘色，`AskCell` 卖盘色）
- `update`：`True` = 数据更新时刷新此列；`False` = 只在新增行时写入（代码、交易所等不变字段）

---

### 阅读文件

- [ ] `vnpy/chart/widget.py` — K线图控件
- [ ] `vnpy/chart/item.py` — K线/成交量图元

### 学习 Checklist

- [ ] 理解 `ChartWidget` 的数据更新接口：`update_history` vs `update_bar`
- [ ] 理解 `CandleItem` 如何用 pyqtgraph 绘制 OHLC K 线
- [ ] 理解时间轴坐标映射：整数索引 → 时间字符串

### 能回答的问题（完成标志）

- [ ] 如何在 K 线图上叠加一条自定义均线？
- [ ] 实时 Tick 推入后，K 线图如何只更新最后一根而不重绘全部？

---

## 第五阶段：策略与回测

> 掌握 A 股组合策略的开发模式与回测分析。
> 预计时间：3-5 天（需要 clone 外部仓库）

### 外部仓库（需单独 clone）

```bash
git clone https://github.com/vnpy/vnpy_portfoliostrategy
git clone https://github.com/vnpy/vnpy_ctabacktester
git clone https://github.com/vnpy/vnpy_datamanager
git clone https://github.com/vnpy/vnpy_scripttrader
git clone https://github.com/vnpy/vnpy_chartwizard
```

### 学习 Checklist

#### vnpy_portfoliostrategy（重点）
- [ ] 理解 `StrategyTemplate` 基类：`on_init`、`on_start`、`on_stop`、`on_tick`、`on_bar`
- [ ] 理解多标的订阅机制：`vt_symbols` 列表
- [ ] 理解回测引擎 `BacktestingEngine`：数据加载 → 策略初始化 → 逐Bar撮合 → 统计
- [ ] 理解回测统计指标：夏普比率、最大回撤、年化收益的计算方式
- [ ] 理解参数优化：穷举法 vs 遗传算法（`vnpy/trader/optimize.py`）

#### vnpy_datamanager（数据管理 UI）
- [ ] 理解数据导入流程：CSV → `BaseDatabase.save_bar_data`
- [ ] 理解数据概览界面：如何展示 `BarOverview`

#### vnpy_ctabacktester（回测 UI）
- [ ] 理解策略类加载机制：扫描策略文件夹动态导入
- [ ] 理解回测结果图表：资金曲线、回撤曲线、参数热力图

#### vnpy_scripttrader（脚本策略）
- [ ] 理解 `ScriptEngine`：同步 API 封装（`get_tick`、`buy`、`sell`）
- [ ] 理解与 CTA 策略的区别：脚本策略无回测支持，适合快速验证逻辑

### 能回答的问题（完成标志）

- [ ] 组合策略中，如何处理某只股票停牌导致的缺 Bar 问题？
- [ ] 回测时的"成交假设"是什么？默认以什么价格成交？
- [ ] 参数优化的遗传算法相比穷举法有什么劣势？

### 实践任务

- [ ] 用 tushare 下载沪深 300 成分股 2020-2024 的日线数据并入库
- [ ] 用 vnpy_datamanager 查看数据完整性
- [ ] 基于 vnpy_portfoliostrategy 写一个简单的"双均线多标的"策略并回测
- [ ] 分析回测结果：夏普比率、最大回撤

---

## 第六阶段：A 股实盘接入（XTP Gateway）

> 理解 C++ API 封装方式，能配置和排查实盘连接问题。
> 预计时间：1 周（需要券商账户）

### 外部仓库（需单独 clone）

```bash
git clone https://github.com/vnpy/vnpy_xtp
git clone https://github.com/vnpy/vnpy_tushare
git clone https://github.com/vnpy/vnpy_xt
```

### 学习 Checklist

#### vnpy_xtp
- [ ] 理解仓库结构：`vnpy_xtp/api/` 是 C++ 封装，`vnpy_xtp/gateway.py` 是 Python 层
- [ ] 理解 `XtpGateway` 如何实现 `BaseGateway` 的 6 个方法
- [ ] 理解回调线程与 EventEngine 的桥接：C++ 回调 → Python GIL → put_event
- [ ] 理解 XTP 的账户类型：普通账户 vs 信用账户（融资融券）
- [ ] 了解 ETF 申购赎回接口（如果需要）

#### A 股特有规则
- [ ] T+1 限制：代码层面如何避免当天买入后卖出？
- [ ] 涨跌停限制：委托价格范围校验
- [ ] 最小交易单位：A 股 100 股/手

#### 数据服务选择
- [ ] **vnpy_tushare**：适合离线历史数据下载，了解 token 配置和频率限制
- [ ] **vnpy_xt**（迅投研）：适合实盘实时行情，了解行情订阅方式

### 能回答的问题（完成标志）

- [ ] XTP 的 `on_trade` 回调是在哪个线程触发的？如何保证线程安全？
- [ ] 如果 Gateway 断线重连，`OmsEngine` 中的持仓数据如何同步？
- [ ] tushare 的日线数据和 XTP 的实时 Tick 数据，时间戳格式是否一致？

### 实践任务

- [ ] 配置 XTP 仿真账户并连接成功
- [ ] 订阅 5 只 A 股的实时 Tick，在 K 线图中显示
- [ ] 用 vnpy_scripttrader 手动发一笔测试委托并确认回报

---

## 第七阶段：AI 投研模块（Alpha）

> 掌握多因子 ML 投研流水线，能扩展自定义因子和模型。
> 预计时间：3-4 天

### 阅读文件

- [ ] `vnpy/alpha/lab.py` — AlphaLab 投研实验室
- [ ] `vnpy/alpha/dataset/template.py` — AlphaDataset 数据集
- [ ] `vnpy/alpha/dataset/utility.py` — 表达式引擎
- [ ] `vnpy/alpha/dataset/datasets/alpha_101.py` — WorldQuant 101 因子
- [ ] `vnpy/alpha/dataset/datasets/alpha_158.py` — Qlib Alpha158 因子
- [ ] `vnpy/alpha/model/template.py` — AlphaModel 抽象
- [ ] `vnpy/alpha/model/models/lgb_model.py` — LightGBM 模型
- [ ] `vnpy/alpha/strategy/template.py` — AlphaStrategy 抽象
- [ ] `vnpy/alpha/strategy/backtesting.py` — 回测引擎

### 学习 Checklist

#### 数据集层
- [ ] 理解 `AlphaDataset.prepare_data()`：日历对齐 → 因子计算 → train/valid/test 分段
- [ ] 理解 `calculate_by_expression()`：表达式引擎如何解析 `"Rank(Corr(Return, Volume, 20))"`
- [ ] 理解 `cs_function`（截面算子）vs `ts_function`（时序算子）的区别
- [ ] 了解 Alpha101 和 Alpha158 各自的设计思路

#### 模型层
- [ ] 理解 `AlphaModel.train()` / `predict()` 统一接口
- [ ] 理解 LightGBM 模型的特征重要性输出
- [ ] 理解 Lasso 模型的特征选择作用

#### 策略层
- [ ] 理解截面多标的策略：按因子得分排序 → 做多前 N%、做空后 N%
- [ ] 理解 `BacktestingEngine` 的换仓逻辑：调仓频率、交易成本
- [ ] 理解 alphalens 分析：IC、ICIR、分层收益

#### AlphaLab 工作流
- [ ] 理解目录约定：`daily/`、`dataset/`、`model/`、`signal/`
- [ ] 理解 Parquet 格式：为什么用 Polars + Parquet 而不是 Pandas + CSV？

### 能回答的问题（完成标志）

- [ ] 什么是因子的 IC（Information Coefficient）？IC > 0.05 意味着什么？
- [ ] 为什么数据要做 `cs_norm`（截面标准化）而不是 `ts_norm`？
- [ ] LightGBM 训练时如何防止过拟合？
- [ ] A 股有涨跌停，回测中如何处理"信号强但买不到"的情况？

### 实践任务

- [ ] 安装 alpha 依赖：`pip install "vnpy[alpha]"`
- [ ] 阅读并运行 `examples/alpha_research/download_data_rq.ipynb`（或 xt 版本）
- [ ] 基于 Alpha158 因子集训练一个 LightGBM 模型
- [ ] 对模型做 alphalens 因子分析，解读 IC 和分层收益图

---

## 参考资源

| 资源 | 链接 |
|------|------|
| 官方文档 | [www.vnpy.com](https://www.vnpy.com) |
| GitHub 主仓库 | [github.com/vnpy/vnpy](https://github.com/vnpy/vnpy) |
| 社区论坛 | [community.vnpy.com](https://community.vnpy.com) |
| XTP 仓库 | [github.com/vnpy/vnpy_xtp](https://github.com/vnpy/vnpy_xtp) |
| CTA 策略仓库 | [github.com/vnpy/vnpy_ctastrategy](https://github.com/vnpy/vnpy_ctastrategy) |
| 组合策略仓库 | [github.com/vnpy/vnpy_portfoliostrategy](https://github.com/vnpy/vnpy_portfoliostrategy) |
| Tushare 数据仓库 | [github.com/vnpy/vnpy_tushare](https://github.com/vnpy/vnpy_tushare) |
| Qlib（对比参考）| [github.com/microsoft/qlib](https://github.com/microsoft/qlib) |

---

## 学习进度记录

| 阶段 | 预计时间 | 实际开始 | 实际完成 | 备注 |
|------|---------|---------|---------|------|
| 第一阶段：基础设施 | 1-2 天 | | | |
| 第二阶段：核心引擎 | 2-3 天 | | | |
| 第三阶段：数据基础设施 | 1-2 天 | | | |
| 第四阶段：可视化界面 | 1 天 | | | |
| 第五阶段：策略与回测 | 3-5 天 | | | |
| 第六阶段：A股实盘接入 | 1 周 | | | |
| 第七阶段：AI 投研 | 3-4 天 | | | |
