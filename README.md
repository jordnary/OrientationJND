# 方位差辨别实验（PsychoPy）

本项目是《L3-Visual System》第 63-66 页作业的可运行基础框架。用两个依次出现的 Gabor 光栅，测量观察者辨别方位差的能力。尚未采集真人数据，当前不包含实验结论。

## 在 Windows 上启动

1. 打开已安装的 **PsychoPy Standalone Coder**；如果当前是 Builder，切换到 Coder。
2. 打开项目中的 `run_experiment.py`，点击运行按钮。请使用 Standalone 自带的 Python，无需在 Miniconda 中安装 PsychoPy。
3. 输入匿名编号，例如 `P001`，首次选择 `demo`。先做 8 个有反馈的练习，再做 24 个无反馈的演示试次。
4. 提示出现后，按 **F = 方位相同**、**J = 方位不同**；空格开始或继续，Esc 退出。比较的是倾斜方向，条纹位置变化不算方位变化。
5. 确认操作和显示正常后，选择 `formal`：默认全屏、8 个练习、144 个正式试次，每 24 个正式试次休息一次。
6. 完成后，在 Coder 中打开并运行 `analyze_results.py`，选择 `data/` 中对应的 `*_trials.csv`，分析结果保存在 `results/<session_id>/`。

如果程序立即结束，请查看 Coder 的输出面板。本项目的报错摘要不会打印本地路径。修改配置出错时，可用 Git 恢复 `config.json`。

## 作业要求与本框架的选择

| 页面 | 内容 | 实现 |
| --- | --- | --- |
| 63 | 用 Gabor 测量方位差辨别能力；关注尺寸、方位、空间频率、对比度 | 正弦光栅 + Gaussian 遮罩；参数集中配置 |
| 64 | 第一刺激 0.5 s、间隔 1 s、第二刺激 0.5 s，判断 Same or not；绘制方位差与正确率的关系 | 中央依次呈现、相同/不同判断、正确率汇总图 |
| 65 | Psychtoolbox 路线 | 本项目选用第 66 页路线 |
| 66 | 学习 PsychoPy JND 教程 | 使用 PsychoPy Coder、刺激绘制、键盘采集与实验循环 |

[官方 Tutorial 2](https://psychopy.org/coder/tutorial2.html) 本身采用**同时左右呈现、选择参考刺激、阶梯法**。本框架为了对应第 64 页时序图，采用**依次呈现、相同/不同判断、恒定刺激法**。两种任务的正确率和阈值定义不同，因此没有直接套用教程的 staircase 阈值。当前未实现阶梯法。

本项目补充的设计选择包括：0.5 s 注视、5 s 作答窗口、0.3 s 试次间隔、8 个练习、按键、方位差档位和重复次数；这些不是课件规定的数值。

## 单个试次

```text
注视 0.5 s
    -> 参考 Gabor 0.5 s
    -> 空屏（保留注视点）1.0 s
    -> 比较 Gabor 0.5 s
    -> F / J 作答，最多 5 s
    -> 练习时反馈 0.6 s
    -> 试次间隔 0.3 s
```

反应时从第二刺激消失、作答提示出现的那一帧开始计算。提前按下的反应键不计入作答；超时记为错误，同时单独标记。练习数据保存，但不进入正式分析。Esc 会保留已完成试次；退出时尚未完成的试次不计入 CSV。

## 配置与试次平衡

编辑 `config.json` 即可修改实验。默认参考方位为 0°，正方向遵循 PsychoPy 的顺时针约定。非零方位差为 0.5°、1°、2°、4°、8°、16°。

每个方位差档位，正式阶段有 12 个“不同”试次（顺/逆时针各 6）以及 12 个配对的“相同”控制试次。因此正式总数为 `6 × (12 + 12) = 144`，两个答案各占一半。全部试次混合随机排列；重复次数必须为偶数。练习仅用最大方位差，便于理解任务。

两次呈现分别随机化光栅相位，避免通过条纹位置是否完全重合判断答案。尺寸、对比度、空间频率保持一致。`condition_delta_deg` 是配对条件标签；“相同”试次的实际 `signed_delta_deg` 始终为 0，不能把条件标签误认为实际方位差。

刺激尺寸目前使用窗口高度单位：`size_height=0.3`；PsychoPy 在 `height` 单位下将光栅 `sf` 解释为整个刺激宽度内的周期数，因此设置 `spatial_frequency_cycles_per_stimulus=7.2`。这些数值**不是 0.3° 视角或 7.2 cycles/degree**；方位旋转角度本身仍以度为单位。演示窗口和正式全屏的物理刺激大小可能不同。

正式比较不同人或不同条件前，应固定屏幕、分辨率、观看距离与环境照明；记录屏幕实际尺寸和观看距离，再按 [PsychoPy 单位文档](https://psychopy.org/general/units.html) 扩展 Monitor 校准和 `deg` 单位。当前框架明确记录 `spatially_calibrated=false`，没有假定显示器参数。

测到稳定刷新率时，短刺激按刷新帧数呈现，保存实际 onset/offset 和长帧计数。若测不到稳定刷新率，改为按已翻转画面的经过时间控制，仅供演示；时长通常比目标多 1-2 次屏幕刷新，不再用假定 60 Hz 的帧数控制刺激。后备刷新率仅用于这种情况下的长帧粗略标记，该次不能用于自动阈值估计。软件时间戳不能替代光电二极管等外部显示计时校验。

## 文件结构

```text
config.json                 参数
run_experiment.py           PsychoPy 实验入口
experiment_core.py          随机化、条件平衡、数据保存
analyze_results.py          汇总、绘图、探索性阈值
tests/test_experiment.py    设计、分析及异常边界检查
docs/report_outline.md      待真实实验后填写的报告提纲
data/                       每次运行的 CSV 和参数 JSON（不提交）
results/                    分析结果（不提交）
tmp/                        自动验证产物（不提交）
```

每个试次结束立即刷新 CSV；同名会话不会被覆盖。JSON 保存参数、随机种子、PsychoPy 版本、刷新率、键盘后端、预期试次数和完成状态，不采集用户名、设备名、目录或虚拟环境信息。仅使用匿名参与者编号；请勿输入真实姓名。

主要数据列包括：实际方位差、两个方位、光栅相位、应答键、正确性、RT、超时、刺激起止时刻与长帧数。`timing_valid` 要求使用稳定刷新率计帧，且两个刺激和间隔的实际时长与计划帧时长之差均不超过 1.5 帧。绝对时刻是 PsychoPy 的软件时钟读数，不是墙钟日期；刺激实际时长由相邻起止时刻之差计算。JSON 的 `completed_trials` 包含练习；分析输出的 `main_trials` 不含练习。

## 分析与阈值的含义

分析输出包括 `accuracy_by_delta.csv`、`summary.json`、`accuracy.png`。

- `different_accuracy`：该非零方位差下，“不同”试次的正确率。
- `same_accuracy_pooled`：所有零方位差控制试次中，回答“相同”的正确率。
- `balanced_accuracy = (different_accuracy + same_accuracy_pooled) / 2`：平衡后的正确率。一直回答同一个键，只能得到 0.5。
- `false_alarm_rate`：实际相同却按 J 的比例。超时是独立类别，不被当作虚报。

将所有“相同”试次合并估计控制正确率，可减少每个难度组控制试次数较少带来的波动。因此图中的各个平衡正确率共享同一控制基线，并不相互独立。

75% 只是当前框架预设的**探索性操作阈值**。仅对完整的 `formal` 会话、已测稳定刷新率、全部主试次计时有效且无长帧记录、每个难度至少 10 个“不同”试次且曲线单调时，在包围 75% 的两个点间做线性插值。演示、样本不足、曲线不单调或测量范围未包住阈值时，不输出数值，不外推。

`estimate_deg=null` 表示没有可报告的估计。`status` 说明原因：`not_eligible`（演示、未完成、刷新率或长帧问题）、`insufficient_trials`、`nonmonotonic_requires_fitting`、`at_or_below_smallest_delta`、`above_largest_delta_or_low_accuracy`。

相同/不同判断会受应答标准影响。上述结果不能直接等同于 2AFC 的 75% JND，也没有拟合置信区间。后续正式报告应根据试测结果调整档位与样本量，并明确统计模型；不应将演示或自动测试当作真人实验。

## 开发验证

逻辑检查不依赖 PsychoPy：

```powershell
python -m unittest discover -s tests -v
```

图形流程检查需使用 Standalone 的 Python，或在 Coder 的运行参数中加入：

```text
--smoke-test
```

它实际创建 PsychoPy 窗口，运行 2 个练习和 4 个主试次，自动生成明确标注 `synthetic=true` 的测试反应，随后退出。全部产物在 `tmp/smoke/`，分析入口会拒绝这种数据。它验证图形流程、计时和保存；真人按键、全屏效果与观看舒适度仍需通过 `demo` 检查。

API 参考：[GratingStim](https://psychopy.org/api/visual/gratingstim.html)、[Keyboard](https://psychopy.org/api/hardware/keyboard.html)、[Window](https://psychopy.org/api/visual/window.html)。
