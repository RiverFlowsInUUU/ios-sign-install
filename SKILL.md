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
| 安装报验证失败 | 描述文件不含该设备 UDID，或 bundle id 与 App ID 不匹配 | 换描述文件或改 bundle id（改 id 要连 appex 一起改） |
| 装完版本号没变 | 你装的是旧包 | `apps query <bundle-id>` 看 `CFBundleVersion` 核对 |

## 装机后的核对

```bash
python -m pymobiledevice3 apps query <bundle-id> | grep -E "CFBundleIdentifier|CFBundleVersion|ApplicationType"
```

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
