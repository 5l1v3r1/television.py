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
    width  = int(clock / height / fps)
    hsync  = { 'len': 6, 'code': 0b001011 }
    runin  = { 'len': 32, 'code': 0x55555555 }
    vsync  = { 'len': 64, 'code': 0x65AEF3153F41C246 }
    clamp  = { 'len': 32, 'code': 0xEAF3927F }
    
    # Frame counter
    frame = 0
    
    # Continuity counter
    cc = 0
    
    # Duobinary mark (1) polarity
    dub_p = -1
    
    # PRNG poly
    poly = 0x7FFF
    
    # Line PRNs
    line_prn = []
    
    def __init__(self):
        # Generate the noise frame
        noise = [self.prng() for _ in range(0, 648 * 625 - 6)]
        
        # Keep just the parts we need
        self.line_prn = [noise[y * 648:y * 648 + 99] for y in range(0, 623)]
    
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
        
        # For D2-MAC the bitrate is half of D-MAC
        code = [b for b in code for _ in (0, 1)]
        
        return code
    
    def interleave(self, packet):
        pkt = [0] * 751
        
        y = 0
        for x in range(0, 751):
            pkt[x] = packet[y]
            
            y += 94
            
            if y >= 751:
                y -= 751
        
        return pkt
    
    def mkframe(self, image):
        
        self.frame += 1
        samples = []
        
        # Dummy packets
        packets = []
        for x in range(0, 82):
            # Generate the header
            pkt  = "{0:010b}".format(1023)[::-1]       # Channel
            pkt += "{0:02b}".format(self.cc & 3)[::-1] # Continuity
            pkt  = self.bch_encode(int(pkt, 2), 23, 12)
            pkt  = self.bits({ 'len': 23, 'code': pkt })
            
            # Generate the dummy data
            pkt += [0] * 728
            
            # Interleave packet
            pkt = self.interleave(pkt)
            
            # Increment the cc
            self.cc += 1
            
            # Append the packet to the list for this frame
            packets += pkt
            
        for line in range(1, self.height + 1):
            
            ### Digital Bits ###
            
            # All lines begin with the line sync word
            if line <= 622:
                # Lines 1-622 alternate between inverted and true
                # With line 1 on an even frame being true, and
                # line 1 on an odd frame being inverted.
                inv = (self.frame + line) & 1
            
            elif line == 623:
                # Line 623 is on an even frame is inverted
                inv = self.frame & 1
            
            else:
                # Line 624 and 625 are true on an even frame,
                # and inverted on an odd frame
                inv = (self.frame + 1) & 1
            
            bits = self.bits(self.hsync, inv)
            
            if line <= 623:
                # Lines 1 - 623 hold packets
                lb = packets[:99] + [0] * (105 - len(bits))
                lb = [a ^ b for a, b in zip(lb, self.line_prn[line - 1])]
                
                bits += lb
                packets = packets[99:]
            
            elif line == 624:
                # Line 624 contains 67 spare bits and the 32-bit clamp marker
                bits += [1, 0] * 33 + [1]
                bits += self.bits(self.clamp)
            
            elif line == 625:
                bits += self.bits(self.runin, self.frame & 1) # CRI Clock run in (32 bits)
                bits += self.bits(self.vsync, self.frame & 1) # FSW Frame sync word (64 bits)
                bits += self.rbits({ 'len': 5, 'code': 0b10101 })   # UDF Unified date and time (5 bits)
                
                # SDF
                sdf  = "{0:016b}".format(0x5A5A)[::-1]    # CHID Channel identification (16 bits)
                sdf += "{0:08b}".format(0b00000000)[::-1] # SDFSCR Services configuration reference
                sdf += "{0:08b}".format(0b00111111)[::-1] # MVSCG Multiplex and video scrambling control
                                                          # bei 4/3 aspect ratio (standard)
                sdf += "{0:020b}".format((self.frame >> 8) & 0xFFFFF)[::-1] # CAFCNT Conditional access frame count (20 bits)
                sdf += "{0:05b}".format(0b11111)[::-1]    # Unallocated
                sdf  = self.bch_encode(int(sdf, 2), 71, 57)
                bits += self.bits({ 'len': 71, 'code': sdf })
                
                # RDF Repeated data frames:
                for b in range(0, 5):
                    rdf  = "{0:08b}".format(self.frame & 0xFF)[::-1] # FCNT (8 bits)
                    rdf += "{0:01b}".format(0)[::-1]                 # UDF (1 bit)
                    rdf += "{0:08b}".format(0x00000000)[::-1]        # TDMCID (8 bits)
                    rdf += "{0:010b}".format(0x3FF)[::-1]            # FLN1 (10 bits)
                    rdf += "{0:010b}".format(0x3FF)[::-1]            # LLN1 (10 bits)
                    rdf += "{0:010b}".format(0x3FF)[::-1]            # FLN2 (10 bits)
                    rdf += "{0:010b}".format(0x3FF)[::-1]            # LLN2 (10 bits)
                    rdf += "{0:011b}".format(0x7FF)[::-1]            # FCP (11 bits)
                    rdf += "{0:011b}".format(0x7FF)[::-1]            # FCP (11 bits)
                    rdf += "{0:01b}".format(self.frame & 1)[::-1]                 # LINKS (1 bit)
                    rdf  = self.bch_encode(int(rdf, 2), 94, 80)
                    bits += self.bits({ 'len': 94, 'code': rdf })
            
            l  = self.duobinary(bits, 0.4)
            l += [0] * (1296 - len(bits) * 2)
            
            ### Analogue Bits ###
            
            iy = -1
            
            if 24 <= line <= 310:
                iy = (line - 24) * 2 + 1
            
            elif 336 <= line <= 622:
                iy = (line - 336) * 2
            
            # Draw an active line
            if iy != -1:
                
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
                            l[236 + ix // 2] += u / 2
                        
                        else:
                            v = 0.927 * (r - y)
                            l[236 + ix // 2] += v / 2
                    
                    l[590 + ix] = y - 0.5
            
            # Lines 23 and 335 must have a black luminance area
            if line == 23 or line == 335:
                for ix in range(0, 697):
                    l[590 + ix] = -0.5
            
            # Line 624 contains the reference levels
            if line == 624:
                # 372 - 533 White Reference
                for ix in range(372, 534):
                    l[ix] = 0.5
                
                # 534 - 695 Black Reference
                for ix in range(534, 696):
                    l[ix] = -0.5
                
                # 696 - 1296 TODO: wobulation
            
            samples += l
        
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

