import serial, struct, time, itertools, os
def crc16(data):
    crc=0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1: crc=(crc>>1)^0xA001
            else: crc >>= 1
    return crc
def req(addr,func,reg,qty=1):
    d=bytes([addr,func,(reg>>8)&0xff,reg&0xff,(qty>>8)&0xff,qty&0xff])
    return d+struct.pack('<H', crc16(d))
def set_de(v):
    try:
        with open('/sys/class/gpio/gpio122/direction','w') as f: f.write('out')
    except Exception: pass
    try:
        with open('/sys/class/gpio/gpio122/value','w') as f: f.write('1' if v else '0')
    except Exception: pass
bauds=[9600,4800,19200,38400]
addrs=list(range(1,6))
funcs=[3,4]
regs=[0,1,2]
de_modes=['none','high','low','pulse']
found=[]
for baud in bauds:
  for addr in addrs:
    for func in funcs:
      for reg in regs:
        for de in de_modes:
          try:
            ser=serial.Serial('/dev/ttyS9',baudrate=baud,bytesize=8,parity='N',stopbits=1,timeout=0.25)
            if de=='high': set_de(1)
            elif de=='low': set_de(0)
            ser.reset_input_buffer(); ser.reset_output_buffer()
            r=req(addr,func,reg,1)
            if de=='pulse':
              set_de(1); time.sleep(0.002)
            ser.write(r); ser.flush()
            if de=='pulse':
              time.sleep(0.002); set_de(0)
            time.sleep(0.05)
            resp=ser.read(7)
            ser.close()
            if resp:
              found.append((baud,addr,func,reg,de,resp.hex()))
              print('RESP',found[-1]); raise SystemExit
          except SystemExit: raise
          except Exception as e:
            pass
print('scan done found',found)
