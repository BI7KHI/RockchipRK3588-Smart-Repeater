import serial, struct, time, sys

def crc16(data):
    crc=0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc=(crc>>1)^0xA001
            else:
                crc >>= 1
    return crc

req=bytes([0x01,0x03,0x00,0x00,0x00,0x01])
req += struct.pack('<H', crc16(req))
print('request', req.hex())
for mode in ['none','de122']:
    try:
        if mode=='de122':
            try:
                with open('/sys/class/gpio/gpio122/direction','w') as f: f.write('out')
            except Exception as e:
                print('gpio122 direction error', e); continue
        ser=serial.Serial('/dev/ttyS9', baudrate=9600, bytesize=8, parity='N', stopbits=1, timeout=1.0)
        if mode=='de122':
            with open('/sys/class/gpio/gpio122/value','w') as f: f.write('1')
        ser.reset_input_buffer(); ser.reset_output_buffer()
        ser.write(req); ser.flush()
        time.sleep(0.03)
        resp=ser.read(7)
        if mode=='de122':
            try:
                with open('/sys/class/gpio/gpio122/value','w') as f: f.write('0')
            except Exception: pass
        print('mode',mode,'recv',resp.hex())
        if len(resp)==7:
            val=(resp[3]<<8)|resp[4]
            print('raw',val,'wind',round(val/10.0,2))
        ser.close()
    except Exception as e:
        print('mode',mode,'error',e)
