---
name: ios-sign-install
description: Windows 上全命令行给 iPhone 签名并装机（zsign + pymobiledevice3），不用 Mac、不开图形签名工具。当需要反复把自签 ipa 装到一台已注册 UDID 的设备、或签名后想先验再装时使用。
---

# iOS 签名 + 数据线装机（Windows 全命令行）

> 这个 skill 由实际项目沉淀而来：一天里为了让一台 Windows 电脑能「打补丁 → 签名 → 装机」
> 闭环，踩过的坑全部记在下面的表里。**它不含任何证书、密码、UDID、bundle id** ——
> 那些属于使用者，放在仓库外。

## 适用 / 不适用

| 适用 | 不适用 |
|---|---|
| 没有 Mac，只有 Windows | 需要提交 App Store 审核 |
| 已有一张带设备 UDID 的描述文件（Ad Hoc / 个人 / 企业） | 只有免费 Apple ID（那要 7 天重签，另一套流程） |
| 要反复装同一个自签包（每改一版都要装） | 设备未越狱且描述文件不含该设备 UDID |
| 想「签完先验、验过再装」 | 需要 p12 分文件下发 entitlements（见「坑 1」） |

## 铁律：签名只换签名，不改 App 的身份

**bundle id 一律保持原样**，不要按证书/描述文件去改。理由：

- bundle id 与描述文件里的 App ID **无关**（已实测：同一份描述文件签过多个不同 id）
- 改了 id = 变成另一个 App：覆盖不了原 App、数据不接续、可能和别的 App 撞 id
- 签名工具默认就不改；**只有你自己传 `-b` 才会改**——所以别传

`deploy.py` 会**对比签名前后的 bundle id**，只要有一个变了就判失败并拒绝安装；
确实需要改时显式加 `--allow-bundle-id-change`。

顺带一句：改了 id 也可能改变 App Group / keychain 这类按身份分配的东西，
让排查变成两变量同时变——这种改动应该在补丁阶段做，而不是签名阶段顺手做。

## 一次性的前置（装一次就够）

1. **Apple 移动设备驱动**：iTunes **桌面版**自带（`AppleMobileDeviceSupport64.msi` + `Bonjour64.msi`）。
   - ⚠️ **Microsoft Store 版 iTunes 不行**，命令行工具认不到。
   - 装没装，看服务：`Apple Mobile Device Service` 在跑就行，不必装 iTunes 本体。
2. **zsign**（开源签名器，Windows 有 x64 构建）
   - 从 GitHub Releases 下 `zsign-windows-x64.zip`，**用官方 `SHA256SUMS.txt` 校验**再解压。
   - 校验价值：这是要拿你私钥跑的程序，别省这一步。
3. **pymobiledevice3**（走 Apple 标准 `installation_proxy` 装机）
   ```
   python -m pip install pymobiledevice3
   ```
4. **p12 密码**：放在环境变量里，**不要写进命令行历史、不要写进仓库**
   ```
   export P12_PASSWORD='***'
   ```

## 材料怎么交给 agent（这条最容易出错）

本 skill **故意不含**证书、密码、UDID、bundle id —— 它们属于使用者，放在仓库外。
所以 agent 第一次跑必然缺材料。它需要的是**四样东西**，但**只有三样该向用户要**：

| 它需要 | 应该怎么问 | 不要这样 |
|---|---|---|
| 要签的 ipa 路径 | 直接问路径 | — |
| p12 路径 | 直接问路径 | — |
| 描述文件路径 | 直接问路径 | — |
| **p12 密码** | 请用户**自己**写进环境变量 / 文件，再说"好了" | ❌ 不要"把密码发给我"，不要要求贴在对话里 |
| 设备 | 请用户插线 + 点信任 + 解锁 | ❌ 不要猜 UDID |

### 推荐的目录布局（全部在仓库外）

```
~/ios-sign/
├── cert.p12
├── app.mobileprovision
├── env.sh          # export P12_PASSWORD='***'   记得 chmod 600
└── in.ipa
```

agent 这样调用，密码不会出现在对话里，也不会出现在命令里：

```bash
set -a; . ~/ios-sign/env.sh; set +a          # 变量注入进程环境，不回显
python deploy.py --ipa ~/ios-sign/in.ipa \
                 --p12 ~/ios-sign/cert.p12 \
                 --profile ~/ios-sign/app.mobileprovision \
                 --out out.ipa --install
```

`set -a` 让 source 进来的变量自动 export；整条命令里只有路径，没有密码值。

### 三条硬规则

1. **缺材料就停在那一步**，不要猜路径、不要拿示例证书顶替、不要"先生成一个自签的试试"。
2. **不主动索要密码明文**。如果已经出现在对话/日志里，提醒用户：该密码视为已泄露。
3. 密码只能经由**环境变量**或 `--password-stdin` 进入进程；不接受出现在 `argv` 里。

## 证书 ≠ 描述文件（最容易混的一件事）

这两样东西经常被口头合称"证书"，但它们的授权范围完全不同：

| | p12（证书） | .mobileprovision（描述文件） |
|---|---|---|
| 是什么 | **团队身份**："我是 team 6WV6FC7B82" | **一份授权书**：哪些设备 + 哪个 App ID + 哪些能力 |
| 范围 | 一个团队，可以签**任意多**个 App | 通常只覆盖**一个 App ID**（或一个通配前缀） |
| 换 App 要不要换 | 不用 | **要**（除非是通配） |

所以"我用这张证书签了好几个 App"完全成立 —— 那是**同一张 p12 + 多份描述文件**。

### 怎么一眼看出这份描述文件能覆盖几个 App

```bash
python -c "import plistlib,sys;raw=open(sys.argv[1],'rb').read();d=plistlib.loads(raw[raw.find(b'<?xml'):raw.rfind(b'</plist>')+8]);print(d['Entitlements']['application-identifier'])" app.mobileprovision
```

| 输出 | 含义 |
|---|---|
| `TEAMID.*`（结尾星号） | **通配**：任意 bundle id 都能签，一份走天下 |
| `TEAMID.com.foo.bar`（具体名字） | **单 App ID**：只覆盖这一个；签别的 App 要另要一份描述文件 |

卖家的"共享签/企业签"通常给通配；"个人签 / UDID 签"通常按 App ID 逐个签发
（`Name` 常常就是设备 UDID）。

### ✅ 已验证：App 的 bundle id 与描述文件的 App ID **无关**

实测（同一份**单 App ID** 的描述文件，签过多个不同 bundle id 的 App，全部装机成功）：

- **bundle id 可以随意改**，改成什么都能装
- 同一份描述文件能签**任意多**个 App
- 所以"换个 App 就要一份新描述文件"是**错的**（这条作者一开始也写错了）

真正被校验的是 **entitlements**：签名时把描述文件里的 `Entitlements` 原样写进二进制
（尤其是 `application-identifier`），而不是把 bundle id 改成 App ID。

### 但有一个真实副作用：所有这样签出来的 App 共用一个身份

因为每个二进制的 `application-identifier` 都等于描述文件里那一个值
（单 App ID 的情况），所以：

- 这些 App 的 **keychain 访问组**、**App Group 容器 ACL** 是同一个身份
- 两个 App 若都用同一个 App Group 名，会互相看得到对方的数据
- 想避免，就要用**通配**描述文件（`TEAMID.*`）—— 那样每个 App 才能拿到自己的 app id

| 描述文件类型 | bundle id | 每个 App 的 `application-identifier` | 隔离性 |
|---|---|---|---|
| 通配 `TEAMID.*` | 随意 | `TEAMID.<自己的 bundle id>` | 好，各 App 独立 |
| 单 App ID `TEAMID.com.x.y` | 随意 | 全部是 `TEAMID.com.x.y` | 差，共用一个身份 |

> 结论：**签名能不能装**只看 entitlements；**装完之后会不会互相串**才看描述文件是通配还是单 App ID。
> 两者都跟 bundle id 无关 —— 所以签名时**不要动 bundle id**（见上面的铁律）。

## 三步（或者一条命令）

```bash
# 0) 确认设备在（返回 [] 就是没连上/没信任/驱动没装）
python -m pymobiledevice3 usbmux list

# 1) 签名
zsign -k cert.p12 -p "$P12_PASSWORD" -m app.mobileprovision -o out.ipa in.ipa

# 2) 验签（装之前，零风险）——看 entitlements 是否与描述文件对得上
python deploy.py --ipa in.ipa --p12 cert.p12 --profile app.mobileprovision \
                 --out out.ipa --verify-only

# 3) 装机
python -m pymobiledevice3 apps install out.ipa
```

`deploy.py` 把 1+2+3 串起来：**签名 → 自检 → 装机**，任一步不过就停在原地，不会把坏包推上去。

```bash
python deploy.py --ipa in.ipa --p12 cert.p12 --profile app.mobileprovision \
                 --out out.ipa --install
```

密码来源优先级：`--password-env NAME`（默认 `P12_PASSWORD`）> `--password-stdin`。**不接受命令行明文密码**（会进 shell 历史和进程列表）。

## 验签到底验什么

装之前能查出来的，都是装之后要重来一遍的。`deploy.py` 会核对：

| 检查 | 不过会怎样 |
|---|---|
| 描述文件里 `application-identifier` 存在 | 装上去必被拒 |
| 每个二进制（主 App + 每个 appex）的 `application-identifier` = 描述文件那个，或以其为前缀 | 扩展拿不到自己的容器 / 被拒 |
| 二进制的 `com.apple.security.application-groups` ⊆ 描述文件的组 | 容器 `containerURL` 返回 nil |
| appex 的 bundle id 以主 App 的 bundle id 为前缀 | 扩展启动即失败 |
| `DER` 权益槽（slot 7）与 XML（slot 5）一致 | iOS 15+ 优先读 DER，只改一份等于没改 |

最后一条是容易被忽略的：**只重写 XML 权益、DER 槽留着旧值，运行时会拿到旧权益。**

## 坑表（全部实测）

| 现象 | 原因 | 处理 |
|---|---|---|
| 图形工具里找不到「用 p12 签名」这一档 | 某些工具（实测 Sideloadly v0.72）**根本没有 p12 模式**，只有 Apple ID / Normal / Ad-hoc / Export | 换 zsign。**判断方法：在它的 exe 里搜 `.p12`，0 次就是没有** |
| `--entitlements` 改了之后三份二进制全变 | zsign 的 `-e` 是**全局**的 | 要「每个 appex 各自的 id」，zsign 做不到，得自己写签名器 |
| 装机后一开就闪退 | 未信任证书 / 缺少 entitlement 导致 `!` 强解包 | 先 设置→通用→VPN与设备管理 点「信任」；再查权益 |
| `usbmux list` 返回 `[]` | 没插/没点信任/锁屏/Store 版 iTunes | 逐个排：线→信任→解锁→驱动 |
| 安装报验证失败 | ① 描述文件不含这台设备的 UDID ② bundle id 与描述文件 App ID 的关系不满足（见「证书 ≠ 描述文件」一节，此条**未验证**）| 先看 UDID；再拿一份匹配的描述文件，或把 bundle id 改成描述文件那个 App ID（appex 要一起改，保持前缀） |
| 装完版本号没变 | 你装的是旧包 | `apps query <bundle-id>` 看 `CFBundleVersion` 核对 |

## 装机后的核对

```bash
python -m pymobiledevice3 apps query <bundle-id> | grep -E "CFBundleIdentifier|CFBundleVersion|ApplicationType"
```

## 边界：什么样的 App 不该接

`deploy.py` 只管签名装机。**要不要改 App 内部逻辑是另一件事**，而且有些类型改了也白改。
下面这些是实测踩过的，遇到就早点说不：

| 类型 | 为什么难 | 判断方法 |
|---|---|---|
| **SwiftUI + `@Observable` + StoreKit 2** | 付费判定是计算属性，被**完全内联**进各个视图；没有独立 getter，也就没有"改一处"的单点 | 导入符号里有 `Observation0A9RegistrarV6access`；且全程序搜不到调用它的读字段小函数 |
| **状态放在第三方 Atom 库（`XxxAtom` 空类型）** | `@Observable` 类 `numFields=0`，值存在全局 store；`hasProFeatures` 这类计算属性读 store，内联后每处都有 `bl`，且**没有任何静态单点** | `__swift5_types` 里能解析出 `XxxAtom` 但 FieldDescriptor `numFields=0`；真实状态字段名（如 `isPro`）在 reflstr 里搜不到 |
| **所有 UI 调用都走 witness table** | SwiftUI 的 `View.body` 通过 `__swift5_proto` 的 conformance 调用，**`bl` 静态追不到**（本项目实测：付费墙视图函数 `bl` 调用者 0 次，只能靠 witness 表） | 目标函数的 `bl` 调用点统计为 0，但函数明显在跑 |
| 付费墙靠 SwiftUI 状态弹出 | 门槛处不直接调视图函数，只置一个 `@State`/`@Published` 标志，静态追不到"谁触发的" | 搜付费墙视图函数的调用点，只有 1 个（视图链内部） |
| 交易由 StoreKit 2 校验 | 交易是 Apple 签名的 JWS，本地伪造不了 | 字符串里有 `Transaction.currentEntitlements` / `VerificationResult` |

**这类 App 的正确结论是"静态手段到顶了"**，不是"再扫一遍就能找到"。
再往下需要动态调试（注入 dylib / lldb），而这两种都要越狱或开发者模式 ——
没有的话，成本远大于收益，应当直接告诉用户。

同理，**不要**用"再跑一遍更大的扫描"当作承诺：先把"为什么静态找不到"讲清楚，
再让对方决定要不要投入。

### 实测账单（Conflux 2.2.3，2026-11-03）

按顺序排掉的路，全部有指令级证据：

| 查了什么 | 结果 | 结论 |
|---|---|---|
| `hasProFeatures` 是不是存储属性 | `__swift5_fieldmd` 里反查不到任何 rel32 指向它；只在 `__LINKEDIT` 出现 1 次（`hasProFeaturesSbv`，demangled 名池） | **计算属性，无字段、无 getter 单点** |
| 有没有 `isPro` 之类的存储字段 | 全程序 15 处 `isPro`，全是 `isProgressive*` / `isPrepare*` 误匹配 | 没有 |
| 状态存哪 | `PremiumTypeAtom` / `PremiumProductsAtom` / `ShowPremiumSheetAtom` 三个类型的 FieldDescriptor `numFields=0` | **值在 Atom 库的全局 store，不在对象里** |
| 能不能改枚举判等 | `PremiumType` FieldDescriptor = `['none','pro','ultra']`（tag 0/1/2），但没有 `Equatable` witness 可改（`__swift5_proto` 里找不到它的 conformance；简单 enum 的 `==` 被内联成 `cmp`） | 没有单点 |
| 能不能追调用链 | 付费墙视图函数 `bl` 调用者 **0 次** | **UI 全走 witness table，静态追不到** |
| 有没有服务器校验 | 全库无 license/activate/verify 类 URL | 纯本地，但本地也无处下手 |

**结论：结构上就是没有静态单点。** 这不是"再扫一遍"能解决的 ——
要动只能动态（注入 dylib / lldb），需要越狱或开发者模式；
或者改 `AtomStore` 的全局字典，静态同样做不到。

## 隐私红线（如果这套流程要进 public 仓库）

**绝不提交**：`*.p12`、`*.mobileprovision`、`*.ipa`、密码、设备 UDID、真实 bundle id / App Group 名。

做法：

- 材料放仓库**外**（例如 `../sign-prep/`），仓库里只放脚本和占位符
- 密码只走环境变量
- 提交前扫一遍：`git ls-files | grep -iE '\.(p12|mobileprovision|ipa|pem|key)$'`
  和 `git grep -nE '[0-9a-f]{8}-[0-9A-F]{16,}|password|passwd'`
- 已经进了历史就很难回收：**密码一旦进过 public 仓库，视为已泄露，换密码/换证书**

## 一条经验（省几个小时）

**装之前先验，比装完再猜便宜一个数量级。**
把「签名后的包里到底写了什么」变成一条命令的输出，就不会出现「装了五版全是空」这种事。
