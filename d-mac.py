#!/usr/bin/python3

#from PIL import Image
from array import array
#import random
import subprocess

class dmac_encode:
    
    # Fixed settings
    clock  = 20.25e6 # MHz
    fps    = 25
    height = 625
    width  = int(clock / height / fps) # 1296
    hsync  = { 'len': 7, 'code': 0b0001011 }
    runin  = { 'len': 32, 'code': 0x55555555 }
    vsync  = { 'len': 64, 'code': 0x65AEF3153F41C246 }
    clamp  = { 'len': 32, 'code': 0xEAF3927F }
    
    # Frame counter
    frame = 0
    
    # Duobinary mark (1) polarity
    dub_p = -1
    
    # PRNG poly
    poly = 0x1FFF
    
    def prng(self):
        b  = self.poly & 1
        b ^= (self.poly >> 14) & 1
        
        self.poly >>= 1
        self.poly |= b << 14
        
        return bool(b)
    
    def bch_encode(self, code, n, k):
        
        g = 0b100001101110111
        
        code <<= (n - k)
        c = code
        
        for x in range(k - 1, -1, -1):
            if c & (1 << (x + (n - k))):
                c ^= g << x
        
        return code ^ c
    
    def bits(self, code, invert = False):
        return [bool(code['code'] >> x & 1) != invert for x in reversed(range(0, code['len']))]
    
    def rbits(self, code, invert = False):
        return [bool(code['code'] >> x & 1) != invert for x in range(0, code['len'])]
    
    def duobinary(self, code, level):
        
        code = list(code)
        
        for x in range(0, len(code)):
            
            b = bool(code[x])
            
            code[x] = level * self.dub_p if b else 0
            
            if not b:
                self.dub_p = -self.dub_p
        
        return code
    
    def mkframe(self, image):
        
        self.frame += 1
        samples = []
        
        for line in range(1, self.height + 1):
            
            if line < 622:
                #bits  = [0]
                bits  = self.bits(self.hsync, (self.frame + line + 1) & 1)
                bits += [self.prng() for x in range(0, 198)]
                bits += [0]
                
                # Calculate the active line
                if 24 <= line <= 310:
                    iy = (line - 24) * 2 + 1
                
                elif 336 <= line <= 622:
                    iy = (line - 336) * 2
                
                else:
                    iy = -1
                
                # Draw the line
                if iy >= 0:
                    
                    chrominance = []
                    luminance = []
                    
                    o = iy * 697 * 3
                    
                    for ix in range(0, 697):
                        r, g, b = image[o:o + 3]
                        o += 3
                        
                        r = r / 255.0
                        g = g / 255.0
                        b = b / 255.0
                        
                        y = 0.299 * r + 0.587 * g + 0.144 * b
                        
                        if ix & 1:
                            if line & 1:
                                u = 0.733 * (b - y)
                                chrominance += [u / 2]
                            
                            else:
                                v = 0.927 * (r - y)
                                chrominance += [v / 2]
                        
                        luminance += [y - 0.5]
                    
                    # Pad out chrominance
                    chrominance += [0]
                
                elif line == 23 or line == 335:
                    chrominance = [0] * 349
                    luminance = [-0.5] * 697
                    
                else:
                    chrominance = [0] * 349
                    luminance = [0] * 697
                
                samples += self.duobinary(bits, 0.4) #    1 -  206: 206 clock periods for data burst (1 bit run-in, 6 bits line sync, 198 data bits, 1 spare bit)
                samples += [0] * 4                   #  207 -  210: 4 clock periods for transition rom end of data
                samples += [0] * 15                  #  211 -  225: 15 clock periods - clamp period (0.5 V)
                samples += [0] * 10                  #  226 -  235: 10 clock periods for weighted transition to colour-difference signal
                samples += chrominance               #  236 -  584: 349 clock periods for colour-difference component
                samples += [0] * 5                   #  585 -  589: 5 clock periods for weighted transition between colour-difference signal and luminance signal
                samples += luminance                 #  590 - 1286: 697 clock periods for luminance signal
                samples += [0] * 6                   # 1287 - 1292: 6 clock periods for weighted transition from luminance signal
                samples += [0] * 4                   # 1293 - 1296: 4 clock periods for transition into data, including one run-in bit
            
            elif line == 622:
                #bits  = [0]
                bits  = self.bits(self.hsync, (self.frame + 1) & 1)
                bits += [self.prng() for x in range(0, 198)]
                bits += [0]
                
                samples += self.duobinary(bits, 0.4) # 1 - 206
                samples += [0] * (1296 - len(bits))
            
            elif line == 623:
                #bits  = [0]
                bits  = self.bits(self.hsync, (self.frame + 1) & 1)
                bits += [self.prng() for x in range(0, 198)]
                bits += [0]
                
                samples += self.duobinary(bits, 0.4) # 1 - 206
                samples += [0] * (1296 - len(bits))
            
            elif line == 624:
                #bits  = [0]
                bits  = self.bits(self.hsync, (self.frame) & 1)
                bits += self.rbits({ 'len': 167, 'code': 0x55555555555555555555555555555555555555555555 })
                bits += self.bits(self.clamp)
                #bits += [0] * (206 - len(bits))
                
                samples += self.duobinary(bits, 0.4) # 1 - 206
                samples += [0] * 3                   # 207 - 209
                samples += [0] * 162                 # 210 - 371 Grey reference
                samples += [0.5] * 162               # 372 - 533 White reference
                samples += [-0.5] * 162              # 534 - 695 Black reference
                samples += [0] * 601                 # 696 - 1296 TODO: wobulation
            
            else:
                #bits  = [0]
                bits  = self.bits(self.hsync, (self.frame) & 1)      # LSW Line sync word (6 bits)
                bits += self.bits(self.runin, (self.frame + 1) & 1)  # CRI Clock run in (32 bits)
                bits += self.bits(self.vsync, (self.frame + 1) & 1)  # FSW Frame sync word (64 bits)
                
                # For D-MAC (not D2-MAC) the bits in idits are interleaved with random data
                ibits = self.rbits({ 'len': 5, 'code': 0b10101 })     # UDF Unified date and time (5 bits)
                
                f  = "{0:016b}".format(0x5A5A)[::-1]    # CHID Channel identification (16 bits)
                f += "{0:08b}".format(0b00000000)[::-1] # SDFSCR Services configuration reference
                f += "{0:08b}".format(0b00111111)[::-1] # MVSCG Multiplex and video scrambling control
                                                        # bei 4/3 aspect ratio (standard)
                f += "{0:020b}".format((self.frame >> 8) & 0xFFFFF)[::-1]   # CAFCNT Conditional access frame count (20 bits)
                f += "{0:05b}".format(0b11111)[::-1]    # Unallocated
                
                # Convert to integer and apply BCH code
                f  = self.bch_encode(int(f, 2), 71, 57)
                
                # Apply to the frame
                ibits += self.bits({ 'len': 71, 'code': f })
                #bits += self.bits({ 'len': 14, 'code': 0b10101001001000 })
                
                # RDF Repeated data frames:
                for b in range(0, 5):
                    
                    # Build up the frame
                    f  = "{0:08b}".format(self.frame & 0xFF)[::-1] # FCNT (8 bits)
                    f += "{0:01b}".format(0)[::-1]                 # UDF (1 bit)
                    f += "{0:08b}".format(0x00000000)[::-1]        # TDMCID (8 bits)
                    f += "{0:010b}".format(0x3FF)[::-1]            # FLN1 (10 bits)
                    f += "{0:010b}".format(0x3FF)[::-1]            # LLN1 (10 bits)
                    f += "{0:010b}".format(0x3FF)[::-1]            # FLN2 (10 bits)
                    f += "{0:010b}".format(0x3FF)[::-1]            # LLN2 (10 bits)
                    f += "{0:011b}".format(0x7FF)[::-1]            # FCP (11 bits)
                    f += "{0:011b}".format(0x7FF)[::-1]            # FCP (11 bits)
                    f += "{0:01b}".format(self.frame & 1)[::-1]                 # LINKS (1 bit)
                    
                    # Convert to integer and apply BCH code
                    f  = self.bch_encode(int(f, 2), 94, 80)
                    
                    # Apply to the frame
                    ibits += self.bits({ 'len': 94, 'code': f })
                    #f += self.bits({ 'len': 14, 'code': 0b10101101000011 })
                
                # Interleave ibits with random data
                rbits = [self.prng() for x in range(0, len(ibits))]
                bits += [_ for _ in zip(ibits, rbits) for _ in _]
                
                bits += [self.prng() for x in range(0, self.width - len(bits))]
                #bits += self.bits({'code': 0, 'len': self.width - len(bits)})
                
                # Write the duoencoded bits to the output
                samples += self.duobinary(bits, 0.4) # 1 - 1296
            
        return samples

# ffmpeg import
command = [
        'ffmpeg',
        '-i', 'sample.mp4',
        '-r', '25',
        '-f', 'image2pipe',
        '-pix_fmt', 'rgb24',
        '-vcodec', 'rawvideo',
#        '-vf', 'crop=ih/3*4:ih,scale=697:574',
        '-vf', 'scale=697:574',
#        '-ss', '8.5',
        '-'
]
pipe = subprocess.Popen(command, stdout = subprocess.PIPE, bufsize = 10 ** 8)

# Encoder loop
t = dmac_encode()
f = open('samples.bin', 'wb')

#im = Image.open('image.png')

# Limit to 30 seconds
for x in range(0, 25 * 60):
    
    # ffmpeg frame to image
    raw_image = pipe.stdout.read(697 * 574 * 3)
    #im = Image.frombytes('RGB', (656, 480), raw_image)
    #im = im.resize((697, 574), Image.ANTIALIAS)
    #im = im.convert('RGB')
    
    r = t.mkframe(raw_image)
    array('f', r).tofile(f)

f.close()

