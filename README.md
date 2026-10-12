# 面向智能体的可解释纠错系统设计与实现

本科毕业设计项目。本仓库当前只包含项目骨架，**尚未实现任何业务功能**。

## 一、项目目标

设计并实现一个面向智能体的可解释纠错系统：当智能体的输出存在错误时，系统能够定位错误、给出可理解的纠错理由，并输出修正后的结果。系统强调「可解释」——每一步判断都要能说明依据，而不是只给一个黑箱结论。

预期涉及的能力（均为后续阶段的目标，本阶段不实现）：

- 智能体：任务编排与模型调用。
- 错误诊断：识别输出中的错误类型与错误位置。
- 自动纠错：生成修正结果并给出纠错理由。
- 日志系统：记录调用过程与中间结果，便于复现与评估。
- Web 界面：提供交互式操作与结果可视化。

## 二、当前阶段

**阶段 0：项目骨架搭建与环境验证。**

已完成的内容：

- 项目目录 `D:\AgentThesis`。
- 虚拟环境 `D:\AgentThesis\.venv`，解释器为 `D:\AgentThesis\.venv\Scripts\python12.exe`（Python 3.12.10，基础安装 `D:\PYTHON12`）。
- 入口脚本 `main.py`：运行时打印项目名称、当前阶段与提示信息。
- 基础测试 `tests\test_environment.py`：使用标准库 `unittest`，校验 `main.py` 存在且 Python 版本不低于 3.12。

本阶段**没有**安装任何第三方依赖，虚拟环境内仅有 `pip`。

## 三、目录结构

```
D:\AgentThesis
├── .venv\                     虚拟环境（不纳入版本管理）
├── README.md                  项目说明
├── main.py                    项目入口（打印项目信息）
└── tests\
    └── test_environment.py    环境与骨架测试
```

## 四、运行方法

在 `D:\AgentThesis` 目录下执行以下命令。由于基础安装的解释器被重命名为 `python12.exe`，虚拟环境中的解释器同样名为 `python12.exe`，**不是** `python.exe`。

运行入口脚本：

```powershell
D:\AgentThesis\.venv\Scripts\python12.exe main.py
```

运行测试：

```powershell
D:\AgentThesis\.venv\Scripts\python12.exe -m unittest discover -s tests -v
```

如需激活虚拟环境（可选）：

```powershell
D:\AgentThesis\.venv\Scripts\Activate.ps1
```

激活后应使用 `python12` 调用解释器；`python` 命令仍会指向系统其它 Python，请注意区分。

## 五、后续计划

1. 阶段 1：明确系统需求与总体架构，确定智能体与纠错模块的接口。
2. 阶段 2：搭建错误诊断模块，定义错误类型体系与数据结构。
3. 阶段 3：实现自动纠错与可解释性输出（纠错理由、证据）。
4. 阶段 4：加入日志与评估，构造测试集衡量纠错效果。
5. 阶段 5：基于 Streamlit 实现交互界面，完成系统集成与论文实验。

依赖将在后续阶段按需引入，届时同步更新本文件。
