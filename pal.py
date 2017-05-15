#!/usr/bin/python3

import numpy as np
#from PIL import Image
import subprocess as sp
#import random

pixel_clock = 16e6
fps = 25
frame_height = 625
coloursub_freq = 4433618.75

# Composite line levels
sync_level = -0.3
black_level = 0.0
white_level = 0.7
colour_level = 0.15

# Timings
line_sync = int(round(4.5e-6 * pixel_clock))
short_sync = int(round(2e-6 * pixel_clock))
long_sync = int(round(27e-6 * pixel_clock))
back_porch = int(round(8e-6 * pixel_clock))
half_line = int(round(32e-6 * pixel_clock))
burst_length = int(round(0.00000225 * pixel_clock))
burst_start = int(round(0.00000560 * pixel_clock))
active_left = int(round(0.00001040 * pixel_clock))
active_width = int(round(0.00005195 * pixel_clock))
active_height = 576

# Pixels per frame and line
line_width = int(round(pixel_clock / fps / frame_height))
frame_length = int(line_width * frame_height)

# Colour/pixel delta
coloursub_delta = 2 * np.pi * coloursub_freq / pixel_clock

# Generate the colour subcarrier lookup table,
# 4 frames worth, after which the carrier repeats
# Appends the first line to make handling overflow easier
try:
	coloursub_lookup = np.load('coloursub_lookup.npy')
except:
	print("Generating colour subcarrier lookup table")
	coloursub_lookup = [np.sin(coloursub_delta * _) for _ in range(0, frame_height * line_width * 4)]
	coloursub_lookup = np.array(coloursub_lookup + coloursub_lookup[:line_width], dtype = 'float32')
	np.save('coloursub_lookup.npy', coloursub_lookup)

# Generate the RGB > YUV level lookup table
try:
	yuv_lookup = np.load('yuv_lookup.npy')
except:
	print("Generating RGB > YUV lookup table")
	yuv_lookup = np.zeros((0x1000000, 3), dtype = 'float32')
	for rgb in range(0x000000, 0x1000000):
		r = ((rgb & 0xFF0000) >> 16) / 255.0
		g = ((rgb & 0x00FF00) >> 8)  / 255.0
		b = ((rgb & 0x0000FF) >> 0)  / 255.0
		
		# Gamma correction
		#r **= 1.0 / 2.2
		#g **= 1.0 / 2.2
		#b **= 1.0 / 2.2
		
		# RGB to YUV
		yuv_lookup[rgb, 0] = 0.299 * r + 0.587 * g + 0.114 * b
		yuv_lookup[rgb, 1] = 0.493 * (b - yuv_lookup[rgb, 0])
		yuv_lookup[rgb, 2] = 0.877 * (r - yuv_lookup[rgb, 0])
	
	np.save('yuv_lookup.npy', yuv_lookup)

def line_phase(frame, line, phase):
	
	# Length of the lookup
	l = frame_height * line_width * 4
	
	# Find the start of the line
	p = (frame_height * (frame & 3) + line) * line_width
	
	# Add the phase offset
	phase %= 360
	
	if phase == 0:
		p += 0
	
	elif phase == 45:
		p += l / 8 * 3
	
	elif phase == 90:
		p += l / 8 * 6
	
	elif phase == 135:
		p += l / 8 * 1
	
	elif phase == 180:
		p += l / 8 * 4
	
	elif phase == 225:
		p += l / 8 * 7
	
	elif phase == 270:
		p += l / 8 * 2
	
	elif phase == 315:
		p += l / 8 * 5
	
	else:
		raise Exception('Invalid phase angle ' + str(phase))
	
	# Limit to the buffer range
	p = int(p)
	if p >= l:
		p -= l
	
	# Return the position in the buffer
	return p

def pal_direction(frame, line):
	
	# Return a flag showing which way this line alternates
	a = (frame * frame_height + line) % 2
	if a == 0: a -= 1
	
	return a

print("Encoding video...")
command = [
	'ffmpeg',
	'-i', 'sample.mp4',
	'-r', str(fps),
	'-f', 'image2pipe',
	'-pix_fmt', 'rgb24',
	'-vcodec', 'rawvideo',
	'-vf', 'scale=%d:%d' % (active_width, active_height),
	'-'
]
pipe = sp.Popen(command, stdout = sp.PIPE)

f = open('samples.bin', 'wb')

# Generate the frames (5 minute max)
for frameno in range(0, 25 * 60 * 5):
	raw_image = pipe.stdout.read(active_width * active_height * 3)
	
	# Initialise blank frame
	frame = np.zeros((frame_height, line_width), dtype='float32')
	
	# Generate long sync pulses
	for x in range(0, int(long_sync)):
		# Top field
		for xx in (0, 1, 2): frame[xx][x] = sync_level
		for xx in (0, 1):    frame[xx][half_line + x] = sync_level
		
		# Bottom field
		for xx in (313, 314):      frame[xx][x] = sync_level
		for xx in (312, 313, 314): frame[xx][half_line + x] = sync_level
	
	# Generate short sync pulses
	for x in range(0, int(short_sync)):
		# Top field
		for xx in (623, 624, 3, 4):         frame[xx][x] = sync_level
		for xx in (622, 623, 624, 2, 3, 4): frame[xx][half_line + x] = sync_level
		
		# Bottom field
		for xx in (310, 311, 312, 315, 316, 317): frame[xx][x] = sync_level
		for xx in (311, 312, 315, 316):           frame[xx][half_line + x] = sync_level
	
	# Generate normal sync pulses
	for y in range(0, 305):
		for x in range(int(line_sync)):
			frame[5 + y][x] = sync_level
			frame[318 + y][x] = sync_level
	
	# Generate the colour burst
	for y in (_ for _ in (range(7, 310), range(320, 622)) for _ in _):
		ph = line_phase(frameno, y, 180 - 45 * pal_direction(frameno, y))
		for x in range(int(burst_start), int(burst_start + burst_length)):
			frame[y][x] += coloursub_lookup[ph + x] * colour_level
	
	# Draw the image into the frame
	p = 0
	for y in range(0, active_height):
		yy = int((23 if y % 2 == 0 else 336) + y / 2)
		ph_u = line_phase(frameno, yy, 0)
		ph_v = line_phase(frameno, yy, 90 * pal_direction(frameno, yy))
		
		for x in range(0, active_width):
			rgb = int.from_bytes(raw_image[p:p + 3], byteorder = 'big', signed = False)
			(cy, cu, cv) = yuv_lookup[rgb]
			p += 3
			
			# X position
			xx = active_left + x
			
			# Create composite sample
			cc  = cy
			cc += cu * coloursub_lookup[ph_u + xx]
			cc += cv * coloursub_lookup[ph_v + xx]
			
			frame[yy][xx] = cc * white_level
	
	# Save this frame to file as a series of 32-bit floats
	a = np.array(frame.flatten(), 'float32')
	frame.tofile(f)

f.close()

