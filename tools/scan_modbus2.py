import serial, struct, time
def crc16(data):
    crc=0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc=(crc>>1)^0xA001 if crc&1 else crc>>1
    return crc
def req(addr,func,reg,qty):
    d=bytes([addr,func,(reg>>8)&0xff,reg&0xff,(qty>>8)&0xff,qty&0xff])
    return d+struct.pack('<H', crc16(d))
for baud in [9600,4800,19200]:
  for addr in list(range(1,6))+[0]:
    for func in [3,4]:
      for qty in [1,2]:
        ser=serial.Serial('/dev/ttyS9',baudrate=baud,timeout=0.35)
        ser.reset_input_buffer(); ser.reset_output_buffer()
        r=req(addr,func,0,qty)
        ser.write(r); ser.flush(); time.sleep(0.1)
        expected=3+2*qty
        resp=ser.read(expected)
        ser.close()
        if len(resp)>1:
          print('candidate',baud,addr,func,qty,'req',r.hex(),'resp',resp.hex())
print('done')
