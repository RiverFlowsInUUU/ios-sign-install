#!/usr/bin/env python3
"""一条命令：签名 -> 自检 -> 装机（Windows / macOS，无需 Xcode）。

设计原则
--------
1. **装之前先验**：签名后的包里到底写了什么，必须是一条命令能看到的输出。
2. **密码不上命令行**：优先用 openssl 把 p12 拆成 PEM，再交给 zsign；
   这样进程列表和 shell 历史里都没有密码。没有 openssl 时退回 `-p`，并明确警告。
3. **任一步不过就停**：不会把验证失败的包推上设备。

用法
----
    export P12_PASSWORD='***'
    python deploy.py --ipa in.ipa --p12 cert.p12 --profile app.mobileprovision \
                     --out out.ipa --install

只验不装：
    python deploy.py --ipa in.ipa --p12 cert.p12 --profile app.mobileprovision \
                     --out out.ipa --verify-only

注意：本文件不含任何证书 / 密码 / UDID / bundle id。使用者把材料放在仓库外。
"""
import argparse
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

SLOT_ENT_XML = 5
SLOT_ENT_DER = 7
CS_CMS_SIGNATURE = 0x1D


# ----------------------------------------------------------------- 读签名里的权益
def _code_signature_blob(data):
    if len(data) < 32 or struct.unpack_from('<I', data, 0)[0] not in (0xFEEDFACF, 0xFEEDFACE):
        return None
    ncmds = struct.unpack_from('<I', data, 16)[0]
    off = 32
    for _ in range(ncmds):
        if off + 8 > len(data):
            return None
        cmd, size = struct.unpack_from('<II', data, off)
        if cmd == CS_CMS_SIGNATURE:
            csoff, cssize = struct.unpack_from('<II', data, off + 8)
            return data[csoff:csoff + cssize] if csoff else None
        off += size
    return None


def entitlements(data):
    """返回 (xml_dict, der_bytes)。任一缺失则为 None。"""
    blob = _code_signature_blob(data)
    if not blob or len(blob) < 12:
        return None, None
    _, _, count = struct.unpack('>3I', blob[:12])
    xml = der = None
    for i in range(count):
        typ, boff = struct.unpack('>2I', blob[12 + i * 8:20 + i * 8])
        if boff + 8 > len(blob):
            continue
        _, length = struct.unpack('>2I', blob[boff:boff + 8])
        payload = blob[boff + 8:boff + length]
        if typ == SLOT_ENT_XML:
            try:
                xml = plistlib.loads(payload)
            except Exception:
                xml = None
        elif typ == SLOT_ENT_DER:
            der = payload
    return xml, der


# ----------------------------------------------------------------- 读描述文件
def read_profile(path):
    raw = open(path, 'rb').read()
    i, j = raw.find(b'<?xml'), raw.rfind(b'</plist>')
    if i < 0 or j < 0:
        raise SystemExit('✗ 描述文件里找不到 plist 段：%s' % path)
    return plistlib.loads(raw[i:j + 8])


# ----------------------------------------------------------------- 枚举包里的二进制
def bundles(zf):
    """返回 [(kind, bundle_dir, info_dict, binary_bytes)]，kind in {'app','appex'}"""
    names = zf.namelist()
    tops = sorted({n.split('/')[1] for n in names
                   if n.startswith('Payload/') and n.count('/') >= 2})
    out = []
    for top in tops:
        if not top.endswith('.app'):
            continue
        base = 'Payload/' + top
        plist_path = base + '/Info.plist'
        if plist_path not in names:
            continue
        info = plistlib.loads(zf.read(plist_path))
        exe = info.get('CFBundleExecutable')
        if exe and (base + '/' + exe) in names:
            out.append(('app', base, info, zf.read(base + '/' + exe)))
        for n in names:
            if not n.startswith(base + '/PlugIns/') or not n.endswith('.appex/Info.plist'):
                continue
            d = n[:-len('/Info.plist')]
            pinfo = plistlib.loads(zf.read(n))
            pexe = pinfo.get('CFBundleExecutable')
            if pexe and (d + '/' + pexe) in names:
                out.append(('appex', d, pinfo, zf.read(d + '/' + pexe)))
    return out


# ----------------------------------------------------------------- 验
def verify(ipa, profile, verbose=True):
    prof = read_profile(profile) if isinstance(profile, str) else profile
    pent = prof.get('Entitlements') or {}
    prof_appid = pent.get('application-identifier')
    prof_groups = set(pent.get('com.apple.security.application-groups') or [])
    problems, notes = [], []
    if not prof_appid:
        problems.append('描述文件没有 application-identifier')

    zf = zipfile.ZipFile(ipa)
    bs = bundles(zf)
    if not bs:
        problems.append('包里找不到 Payload/*.app')
    main_bid = next((i.get('CFBundleIdentifier') for k, _, i, _ in bs if k == 'app'), None)

    rows = []
    for kind, d, info, binbytes in bs:
        bid = info.get('CFBundleIdentifier')
        xml, der = entitlements(binbytes)
        tag = d.split('/')[-1]
        if xml is None:
            problems.append('%s 读不到 XML 权益（签名缺失？）' % tag)
            rows.append((tag, bid, '-', '-', '-'))
            continue
        aid = xml.get('application-identifier')
        groups = set(xml.get('com.apple.security.application-groups') or [])
        rows.append((tag, bid, aid, len(groups), 'DER ok' if der else '无 DER 槽'))

        if prof_appid and aid:
            if not (aid == prof_appid or aid.startswith(prof_appid + '.')):
                problems.append('%s 的 application-identifier 与描述文件不匹配\n'
                                '      包内 %s\n      描述文件 %s' % (tag, aid, prof_appid))
        elif not aid:
            problems.append('%s 没有 application-identifier' % tag)

        extra = groups - prof_groups
        if extra:
            problems.append('%s 声明了描述文件没授权的组：%s' % (tag, sorted(extra)))
        if groups and not prof_groups:
            problems.append('%s 带组权益，但描述文件一组都没给' % tag)

        if kind == 'appex' and main_bid and bid and not bid.startswith(main_bid + '.'):
            problems.append('%s 的 bundle id 不是主 App 的前缀：%s vs %s' % (tag, bid, main_bid))

        if der:
            # DER 是 ASN.1，字符串以 UTF8String 原样存放，做子串比对即可
            if prof_appid and prof_appid.encode() not in der:
                problems.append('%s 的 DER 权益槽里没有 %s —— '
                                '可能只重写了 XML，运行时会读到旧权益' % (tag, prof_appid))
            for g in sorted(groups):
                if g.encode() not in der:
                    problems.append('%s 的 DER 权益槽缺组 %s' % (tag, g))
        else:
            notes.append('%s 没有 DER 权益槽（旧签名通常如此，可接受）' % tag)

    if verbose:
        print('  %-28s %-46s %-42s %s' % ('bundle', 'CFBundleIdentifier',
                                          'application-identifier', '组 / DER'))
        for tag, bid, aid, ng, derinfo in rows:
            print('  %-28s %-46s %-42s %s / %s' % (tag, bid or '-', aid or '-', ng, derinfo))
        if prof_groups:
            print('  描述文件授权组 %d 个' % len(prof_groups))
        for n in notes:
            print('  · ' + n)
    return problems


# ----------------------------------------------------------------- 签
def find_zsign(explicit=None):
    """按 ZSIGN -> PATH -> 常见相对路径 的顺序找 zsign。"""
    cands = [explicit, os.environ.get('ZSIGN'), 'zsign', 'zsign.exe']
    here = os.path.dirname(os.path.abspath(__file__))
    roots = [os.getcwd(), os.path.dirname(os.path.dirname(here))]
    for r in roots:
        cands += [os.path.join(r, 'zsign'), os.path.join(r, 'zsign.exe'),
                  os.path.join(r, 'tools', 'zsign'), os.path.join(r, 'tools', 'zsign.exe')]
    for c in cands:
        if not c:
            continue
        if os.path.isfile(c):
            return os.path.abspath(c)
        w = shutil.which(c)
        if w:
            return w
    return None


def sign(ipa, p12, profile, out, password, zsign=None):
    zsign = find_zsign(zsign)
    if not zsign:
        raise SystemExit('✗ 找不到 zsign。三种办法任选：\n'
                         '    1) ZSIGN=/path/to/zsign\n'
                         '    2) 把 zsign 放进 PATH\n'
                         '    3) 放在当前目录或 <repo>/tools/ 下')
    tmp = tempfile.mkdtemp(prefix='sign-')
    try:
        pkey = os.path.join(tmp, 'key.pem')
        cert = os.path.join(tmp, 'cert.pem')
        openssl = shutil.which('openssl')
        env = dict(os.environ, P12_PASSWORD=password or '')
        used_openssl = False
        if openssl and password is not None:
            for args in (
                [openssl, 'pkcs12', '-in', p12, '-nocerts', '-nodes',
                 '-passin', 'env:P12_PASSWORD', '-out', pkey],
                [openssl, 'pkcs12', '-in', p12, '-nokeys', '-clcerts',
                 '-passin', 'env:P12_PASSWORD', '-out', cert],
            ):
                r = subprocess.run(args, env=env, capture_output=True)
                if r.returncode != 0:
                    raise SystemExit('✗ 用 openssl 解 p12 失败（密码不对？）\n'
                                     + r.stderr.decode('utf-8', 'replace')[:400])
            used_openssl = True
            cmd = [zsign, '-k', pkey, '-c', cert, '-m', profile, '-o', out, ipa]
        else:
            print('  ⚠ 没有 openssl，密码会出现在进程参数里（-p）')
            cmd = [zsign, '-k', p12, '-p', password or '', '-m', profile, '-o', out, ipa]
        print('  → ' + ' '.join(c if c != (password or '') else '***' for c in cmd))
        r = subprocess.run(cmd, capture_output=True)
        out_txt = (r.stdout + r.stderr).decode('utf-8', 'replace')
        if r.returncode != 0 or not os.path.exists(out):
            raise SystemExit('✗ 签名失败\n' + out_txt[-1200:])
        print('  ✓ 签名完成：%s（%s）' % (out, 'PEM 方式，密码未进 argv'
                                        if used_openssl else 'p12 方式'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


# ----------------------------------------------------------------- 装
def install(ipa, udid=None):
    exe = [sys.executable, '-m', 'pymobiledevice3']
    r = subprocess.run(exe + ['usbmux', 'list'], capture_output=True)
    txt = (r.stdout + r.stderr).decode('utf-8', 'replace').strip()
    if r.returncode != 0:
        raise SystemExit('✗ pymobiledevice3 不可用：\n' + txt[:400])
    if txt.endswith('[]') or txt.strip() == '[]':
        raise SystemExit('✗ 没检测到设备。检查：数据线 / 手机上点「信任」/ 解锁 / Apple 驱动')
    print('  设备：' + ' '.join(l for l in txt.splitlines() if 'DeviceName' in l or 'ProductVersion' in l))
    cmd = exe + ['apps', 'install', ipa] + (['--udid', udid] if udid else [])
    print('  → 上传并安装（几十 MB，约几秒）')
    r = subprocess.run(cmd, capture_output=True)
    txt = (r.stdout + r.stderr).decode('utf-8', 'replace')
    if r.returncode != 0 or 'Installation succeed' not in txt:
        raise SystemExit('✗ 安装失败\n' + txt[-1500:])
    print('  ✓ Installation succeed')


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description='签名 -> 自检 -> 装机')
    ap.add_argument('--ipa', required=True, help='输入 ipa')
    ap.add_argument('--p12', required=True, help='证书')
    ap.add_argument('--profile', required=True, help='描述文件 .mobileprovision')
    ap.add_argument('--out', default=None, help='输出 ipa（默认 <输入>_signed.ipa）')
    ap.add_argument('--password-env', default='P12_PASSWORD', help='存密码的环境变量名')
    ap.add_argument('--password-stdin', action='store_true', help='从 stdin 读一行密码')
    ap.add_argument('--install', action='store_true', help='签名+验过之后装机')
    ap.add_argument('--verify-only', action='store_true', help='只验一个已有的签名包')
    ap.add_argument('--udid', default=None, help='多设备时指定')
    ap.add_argument('--zsign', default=None, help='zsign 路径')
    a = ap.parse_args()

    for p in (a.ipa, a.p12, a.profile):
        if not os.path.exists(p):
            raise SystemExit('✗ 文件不存在：%s' % p)

    out = a.out or (os.path.splitext(a.ipa)[0] + '_signed.ipa')

    if a.verify_only:
        print('== 验证 %s' % (a.out or a.ipa))
        target = a.out or a.ipa
        problems = verify(target, a.profile)
        print('\n  %s' % ('✓ 通过，可以装' if not problems else '✗ %d 个问题：' % len(problems)))
        for p in problems:
            print('    - ' + p)
        return 0 if not problems else 1

    password = None
    if a.password_stdin:
        import getpass
        password = getpass.getpass('p12 密码: ')
    else:
        password = os.environ.get(a.password_env)
        if password is None:
            print('  · 环境变量 %s 未设置，按空密码尝试' % a.password_env)

    print('== 签名')
    sign(a.ipa, a.p12, a.profile, out, password, a.zsign)

    print('== 验证 %s' % out)
    problems = verify(out, a.profile)
    if problems:
        print('\n  ✗ %d 个问题，不装：' % len(problems))
        for p in problems:
            print('    - ' + p)
        return 1
    print('\n  ✓ 通过')

    if a.install:
        print('== 装机')
        install(out, a.udid)
    else:
        print('  · 没加 --install，只出包不装')
    return 0


if __name__ == '__main__':
    sys.exit(main())
