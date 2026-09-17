import serial, struct, time
def crc16(data):
    crc=0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8): crc=(crc>>1)^0xA001 if crc&1 else crc>>1
    return crc
def req(addr=1,func=3,reg=0,qty=1):
    d=bytes([addr,func,(reg>>8)&0xff,reg&0xff,(qty>>8)&0xff,qty&0xff])
    return d+struct.pack('<H',crc16(d))
ser=serial.Serial('/dev/ttyS9',baudrate=9600,bytesize=8,parity='N',stopbits=1,timeout=0.1)
ser.reset_input_buffer(); ser.reset_output_buffer()
r=req(); print('TX',r.hex()); ser.write(r); ser.flush()
buf=b''; t0=time.time()
while time.time()-t0<2.5:
    b=ser.read(256)
    if b:
        buf+=b
        print(f'RX +{time.time()-t0:.3f}s {b.hex()}')
    time.sleep(0.02)
ser.close()
print('RAW TOTAL',buf.hex(),len(buf))
# scan for 01 03 02
for i in range(len(buf)-6):
    if buf[i]==1 and buf[i+1]==3:
        frame=buf[i:i+7]
        calc=crc16(frame[:-2]); got=frame[-2]|(frame[-1]<<8)
        print('candidate',i,frame.hex(),'crc_ok',calc==got,'raw',(frame[3]<<8)|frame[4])
