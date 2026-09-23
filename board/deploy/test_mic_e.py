#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mic-E 解码验证。

判据来自两个互相独立的来源：
  A. 操作者手台发出的**真实空口报文**（dest=RSPRV4）——应解到广州。
     反例判据：若把 'A'-'J'/'P'-'Y' 的数字误当成从 1 起算，会解成南半球
     或纬度 34°N，因此这条测试能捕获最常见的极性/偏移错误。
  B. **direwolf 自带的测试报文** N1ZZN-9>T2SP0W —— 应解到马萨诸塞州
     （42.50N / 71.13W），南北与东西半球都必须正确。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or '/tmp')
import aprs_service_mice as A


def near(a, b, tol=0.01):
    return a is not None and abs(a - b) <= tol


def check(name, cond, detail=''):
    print('   %-4s %-46s %s' % ('OK' if cond else 'FAIL', name, detail))
    return bool(cond)


def main():
    ok = True

    print('=== A. 真实空口报文（操作者手台，dest=RSPRV4）===')
    # 必须用**完整 50 字节**帧（含尾部 FCS）；只贴前 37 字节会让 parse_frame
    # 剥 FCS 后 info 只剩 5 字节，直接触发长度保护而解不出——曾因此误判。
    hexstr = ('A4A6A0A4AC686084926E96909260AE92888A624062AE92888A644063'
              '03F0602933486C677D292F372E3230562234277D8058')
    assert len(bytes.fromhex(hexstr)) == 50, '测试向量必须是完整帧'
    rec = A.parse_packet(bytes.fromhex(hexstr))
    print('   src=%s dst=%s dtype=%s' % (rec['src'], rec['dst'], rec['dtype']))
    print('   lat=%s lon=%s sym=%s%s course=%s speed=%skt' % (
        rec.get('lat'), rec.get('lon'), rec.get('symbol_table'),
        rec.get('symbol_code'), rec.get('course'), rec.get('speed_kt')))
    print('   comment=%r  status=%s' % (rec.get('comment'), rec.get('mice_status')))
    ok &= check('识别为 Mic-E', rec['dtype'] == 'mice')
    ok &= check('纬度 ≈ 23.0440（广州）', near(rec.get('lat'), 23.0440),
                '实得 %s' % rec.get('lat'))
    ok &= check('经度 ≈ 113.3907（广州）', near(rec.get('lon'), 113.3907),
                '实得 %s' % rec.get('lon'))
    ok &= check('北半球', rec.get('mice_lat_ns') == 'N')
    ok &= check('东半球', rec.get('mice_lon_ew') == 'E')
    ok &= check('经度 +100 偏移位移位=1', rec.get('mice_lon_offset') == 1)
    ok &= check('不是南半球（反例判据）', (rec.get('lat') or 0) > 0)
    ok &= check('目的地址回填', rec.get('mice_dest') == 'RSPRV4')

    print('=== B. direwolf 自带测试报文 N1ZZN-9>T2SP0W（马萨诸塞州）===')
    frames = [
        "N1ZZN-9>T2SP0W:`c_Vm6hk/`\"49}Jeff Mobile_%",
        "N1ZZN-9>T2SP0W:`c_Vm6hk/]\"49}TM-D700 MObile Radio",
        "N1ZZN-9>T2SP0W:'c_Vm6hk/`\"49}Byonics TinyTrack3|3",
    ]
    for txt in frames:
        pkt = A.build_frame('N1ZZN-9'.split('-')[0], 'T2SP0W', [],
                            txt.split(':', 1)[1].encode('latin-1'))
        r = A.parse_packet(pkt)
        good = (r['dtype'] == 'mice' and near(r.get('lat'), 42.5012)
                and near(r.get('lon'), -71.1263))
        ok &= check('%.40s' % txt, good,
                    'lat=%s lon=%s' % (r.get('lat'), r.get('lon')))

    print('=== C. 半球与边界 ===')
    # dest[3] 为数字 => 南；dest[5] 为 'P'-'Z' => 西
    r = A.parse_mic_e('T2SP05', '`c_Vm6hk/`"49}x')     # dest[5]='5' 数字 => 东
    ok &= check("dest[5]='5' -> 东", r.get('mice_lon_ew') == 'E')
    r = A.parse_mic_e('T2SR0W', '`c_Vm6hk/`"49}x')     # dest[3]='R' => 北
    ok &= check("dest[3]='R' -> 北", r.get('mice_lat_ns') == 'N')
    r = A.parse_mic_e('T2S50W', '`c_Vm6hk/`"49}x')     # dest[3]='5' 数字 => 南
    ok &= check("dest[3]='5' -> 南 (且纬度为负)",
                r.get('mice_lat_ns') == 'S' and (r.get('lat') or 0) < 0)
    r = A.parse_mic_e('T2SP0Z', '`c_Vm6hk/`"49}x')     # dest[5]='Z' => 西
    ok &= check("dest[5]='Z' -> 西 (且经度为负)",
                r.get('mice_lon_ew') == 'W' and (r.get('lon') or 0) < 0)

    print('=== D. 消息位（K=自定义集 / Z=标准集）===')
    r = A.parse_mic_e('KSPRV4', '`c_Vm6hk/`"49}x')
    ok &= check("dest[0]='K' -> 自定义集位 4", r.get('mice_cust_msg') == 4,
                'status=%s' % r.get('mice_status'))
    r = A.parse_mic_e('RSPRV4', '`c_Vm6hk/`"49}x')
    ok &= check('全数字目的地址 -> 消息位全 0（不误报）',
                r.get('mice_std_msg') == 0 and r.get('mice_cust_msg') == 0)

    print('=== E. 健壮性：不因畸形输入抛异常 ===')
    for bad in ('', '`', '`abc', '`\\x00\\x01\\x02\\x03\\x04\\x05\\x06\\x07\\x08'):
        try:
            A.parse_mic_e('RSPRV4', bad)
            A.parse_info(bad, 'RSPRV4')
            ok &= True
        except Exception as e:
            ok &= check('畸形输入 %r 不应抛异常' % bad[:10], False, repr(e))
    print('   畸形输入处理：无异常')

    print('=== F. 常规报文不受影响（回归）===')
    f = A.build_frame('BI7KHI', 'APRS', [('WIDE1', 1)],
                      A.aprs_position(22.5333, 114.05, '/', '-', 'test'), src_ssid=10)
    r = A.parse_packet(f)
    ok &= check('普通位置报文仍正确', near(r.get('lat'), 22.5333) and r['dtype'] == 'position',
                'lat=%s dtype=%s' % (r.get('lat'), r['dtype']))
    f = A.build_frame('BI7KHI', 'APRS', [],
                      A.aprs_weather({'temp_c': 20}, 22.5, 114.0, '/', '_', 'WX'), src_ssid=10)
    r = A.parse_packet(f)
    ok &= check('气象报文仍正确', r['dtype'] == 'weather' and r.get('wx'),
                'dtype=%s wx=%s' % (r['dtype'], bool(r.get('wx'))))

    print('\n=== Mic-E 验证结果：%s ===' % ('全部通过' if ok else '存在失败'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
