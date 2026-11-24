# Moonfall 联调启动说明

仓库：<https://github.com/TeresaPeng-zju/lunar-evacuation-race>

分支：`codex/hardware-sandbox`

环境：Node.js 20 或更高版本，支持 WebGL 的桌面浏览器。运行联调不需要 Blender、Unity 或额外构建。

## 1. 首次下载与启动

```sh
git clone --depth 1 --branch codex/hardware-sandbox https://github.com/TeresaPeng-zju/lunar-evacuation-race.git
cd lunar-evacuation-race
npm ci
npm start
```

以后在仓库目录执行 `npm start` 即可。服务默认使用内置无电机模拟器。更新前停止服务，在无本地代码改动的情况下执行 `git pull --ff-only` 和 `npm ci`，再启动。

| 屏幕 | 地址 | 内容 |
| --- | --- | --- |
| 电脑屏 | <http://127.0.0.1:4174/sandbox.html> | 完整 3D 基地、比赛状态、选路、落石和工作人员控制 |
| 27 寸行驶屏 | <http://127.0.0.1:4174/floor.html> | 实体机器人实际行驶的月面主赛区，三段背景与动态道路按各车进度切换 |

电脑显示设置选择“扩展显示”。先打开电脑控制台，点击“打开行驶屏”，将新窗口拖到 27 寸屏，再点击“全屏赛区”。行驶屏含完整月面、设施、信标、舱门、月震和终点；网格及车体包络仅在“坐标检查”时显示。

电脑端点击“配置地图”，等待定位与地图确认；双方选开局路线，再点击“双车发车”。模拟器可选 4× / 8× 加速及固定余震结果，便于验证完整一局。比赛结束后可重置下一局。

只保留一个主控窗口；额外控制台只读。关闭或刷新主控会使运行中的比赛暂停，恢复须按控制台的状态核对流程操作。行驶屏只订阅状态，不发送控制命令。`index.html` 是独立虚拟试玩，硬件联调使用上表入口。

## 2. 通过 WebSocket 联调，不连接电机

先用 `Ctrl+C` 停止前面的服务。终端一：

```sh
npm run hardware
```

终端二，在同一仓库目录运行参考硬件客户端：

```sh
npm run mock
```

浏览器入口不变。这时定位和执行回执通过真实 WebSocket 往返；mock 不驱动电机。先验证握手、配置地图、发车、落石绕行、换段、月震选路、终点停车和暂停恢复，再接入实际硬件程序。

## 3. 接入真实相机与小车

1. 停止 mock 和原服务。每次只允许一个硬件适配器连接，由它汇总两辆车。
2. 复制 `config/hardware.example.json` 为 `config/hardware.local.json`，填写实测标定与控制参数。本机配置不提交到 Git。
3. 在仓库目录启动：

```sh
npm run hardware -- --profile config/hardware.local.json
```

4. 硬件适配器连接 `ws://127.0.0.1:4174/hardware`，按 [完整协议](hardware-integration.md) 完成 `hardware.hello`、时钟同步、地图及路线回执，持续上传车体中心位姿。游戏端给出路线，硬件端负责沿路线行驶、原地回转、制动和本地失联停车。

协议版本为 `lunar-hw/0.3-sandbox`；地图版本为 `physical-v0.3-sandbox.1`。坐标单位 cm，左上角为原点，X 向右、Y 向下；朝右为 0°，顺时针为正。

当前地图约束为有效屏面 59.8 × 33.6 cm、车体 6 × 6 cm、可原地回转、最高速度 2 cm/s。实车发车还会校验标定编号、综合误差、制动距离、定位时效和并列判定窗口。模板中的空值必须通过实测填写，不能直接将 `parameters_verified` 改成 `true`。全屏后的有效显示矩形必须与相机标定一致。

服务只监听本机 `127.0.0.1`，适用于 USB 相机和硬件适配器运行在展示电脑上的方案。其他电脑不能直接用此地址连接；跨电脑通信需单独配置网络方案。

## 4. 排查与交接

| 情况 | 操作 |
| --- | --- |
| 端口已被占用 | 检查已有服务，或用 `npm start -- --port 4175`；外部模式用 `npm run hardware -- --port 4175`，实车时同时保留 `--profile` 参数。浏览器和适配器均改用相同端口 |
| mock 使用其他端口 | `npm run mock -- ws://127.0.0.1:4175/hardware` |
| 想检查实际厘米位置 | 电脑端展开“厘米坐标与车体包络检查”；行驶屏点击“坐标检查”，或打开 `floor.html?debug=1` |
| 操作按钮只读 | 检查是否已有主控窗口，不要另开一套服务来恢复同一场比赛 |
| 页面显示失联 | 检查 Node 服务、WebSocket 和硬件连接；先核对状态，再恢复比赛 |
| 导出正式路径 | <http://127.0.0.1:4174/api/map>；硬件按此配置及路线消息执行，不通过识别背景颜色寻路 |
| 导出排查记录 | <http://127.0.0.1:4174/api/trace>；同时记录复现步骤、比赛阶段及硬件日志 |
| 运行软件回归 | `npm test` |

已提供软件模拟及接口测试；工业相机标定、AprilTag 定位、实车路径跟踪、卡牌识别和本地保护仍由硬件端接入并现场验收。GitHub Pages 仅能展示静态页面，不提供联调服务。

完整字段、消息顺序和异常处理见 [硬件联调接入说明](hardware-integration.md)；双屏换段与坐标映射见 [双屏运行说明](dual-screen.md)。

## NFC 选路与外接双车执行器

启用 `MOONFALL_NFC_START=1` 后，每车刷一张开局路线牌和一张末段路线牌。电脑端 `4264` 显示赛场，手机连接电脑的局域网地址及读卡端口 `4266`。刷齐后，到管理员控制台配置地图并点击「双车发车」。本模式沿选定路线通过三段赛道，保留两次回转。

```sh
MOONFALL_NFC_START=1 npm run hardware -- --port 4264
# 在另一个终端连接采用模拟轮速与位姿的同一套执行器
npm run executor -- ws://127.0.0.1:4264/hardware
```

在这套固定 NFC 路线中，给执行器添加 `--right-angle` 可按原始拐点逐段行驶。车辆到达中间拐点后先停稳，原地对齐下一段方向，再继续直行。每局仍在两处阶段交接点做 180° 回转。实车模式把 `--right-angle` 放在 `--live` 前。

实车联调时，先实测并补齐 `config/dual-executor.example.json` 中的标定和车辆参数，保存为本机配置。确认相机服务 `http://127.0.0.1:4182/live-frame` 提供标签定位，两台车的 `/status` 可达。游戏服务添加 `--profile` 指向该配置，执行器使用 `npm run executor -- --live config/dual-executor.local.json ws://127.0.0.1:4264/hardware`。发车前在控制台核对两车定位、朝向、起点和停稳状态。
