import sys, pyrr
import traceback

from enum import IntEnum

from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5 import QtWidgets

from OpenGL.GL import *
from OpenGL.GLUT import *
from OpenGL.GLU import *
from OpenGL.arrays import vbo
from OpenGL.GL import shaders

from numpy import array, pi, cos, sin
tau = 2*pi

from memorylib import Dolphin

PlaneType = IntEnum('SurfaceType', 'FLOOR WATER ROOF WALLZ WALLX CUBE HITBOX')

class CollisionViewer(QtWidgets.QOpenGLWidget):
	gpCamera = 0
	gpCubeFastA = 0
	gpMapCollisionData = 0
	gpMarioOriginal = 0

	def __init__(self, dolphin: Dolphin, parent=None):
		self.dolphin = dolphin
		self.parent = parent
		QtWidgets.QOpenGLWidget.__init__(self, parent)
		self.resize(800, 600)
		self.frameSwapped.connect(self.update)

	def initializeGL(self) -> None:
		glEnable(GL_BLEND)
		glEnable(GL_CULL_FACE)
		glEnable(GL_DEPTH_TEST)
		glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
		glClearColor(0.7, 0.7, 1.0, 0.0)

		self.shader = shaders.compileProgram(
				shaders.compileShader("""#version 330 core
				uniform mat4 projMat;
				uniform mat4 viewMat;

				layout (location = 0) in vec3 position;
				layout (location = 1) in float type;

				out vec4 vBorderColor;
				out vec4 vVertexColor;

				void main() {
					gl_Position = projMat * viewMat * vec4(position, 1.0);

					vBorderColor = vec4(0, 0, 0, 1);
					
					if (type == """ + str(int(PlaneType.FLOOR)) + """) {
						vVertexColor = vec4(0, 0, 1, 1);
					} else if (type == """ + str(int(PlaneType.WATER)) + """) {
						vVertexColor = vec4(0, 1, 1, 1); // TODO: transparency without breaking the depth test
					} else if (type == """ + str(int(PlaneType.ROOF)) + """) {
						vVertexColor = vec4(1, 0, 0, 1);
					} else if (type == """ + str(int(PlaneType.WALLZ)) + """) {
						vVertexColor = vec4(0, 1, 0, 1);
					} else if (type == """ + str(int(PlaneType.WALLX)) + """) {
						vVertexColor = vec4(0, 0.5, 0, 1);
					} else if (type == """ + str(int(PlaneType.CUBE)) + """) {
						vBorderColor = vVertexColor = vec4(1, 0.5, 0, 0.5);
					} else if (type == """ + str(int(PlaneType.HITBOX)) + """) {
						vBorderColor = vVertexColor = vec4(1, 0, 1, 0.5); // TODO
					} else {
						vVertexColor = vec4(0.5, 0.5, 0.5, 1);
					}
				}""", GL_VERTEX_SHADER),
				shaders.compileShader("""#version 330 core
				layout(triangles) in;
				layout(triangle_strip, max_vertices = 3) out;

				in vec4 vBorderColor[3];
				in vec4 vVertexColor[3];
				out vec3 gTriDistance;
				out float gTriSize;
				out vec4 gBorderColor;
				out vec4 gVertexColor;

				void main() {
					gTriSize = max(max(distance(gl_in[0].gl_Position, gl_in[1].gl_Position),
							distance(gl_in[0].gl_Position, gl_in[2].gl_Position)),
							distance(gl_in[1].gl_Position, gl_in[2].gl_Position));

					gTriDistance = vec3(1, 0, 0);
					gBorderColor = vBorderColor[0];
					gVertexColor = vVertexColor[0];
					gl_Position = gl_in[0].gl_Position;
					EmitVertex();

					gTriDistance = vec3(0, 1, 0);
					gBorderColor = vBorderColor[1];
					gVertexColor = vVertexColor[1];
					gl_Position = gl_in[1].gl_Position;
					EmitVertex();

					gTriDistance = vec3(0, 0, 1);
					gBorderColor = vBorderColor[2];
					gVertexColor = vVertexColor[2];
					gl_Position = gl_in[2].gl_Position;
					EmitVertex();

					EndPrimitive();
				}""", GL_GEOMETRY_SHADER),
				shaders.compileShader("""#version 330 core
				in vec3 gTriDistance;
				in float gTriSize;
				in vec4 gBorderColor;
				in vec4 gVertexColor;
				out vec4 color;

				float amplify(float d, float scale, float offset) {
					d = scale * d + offset;
					d = clamp(d, 0, 1);
					d = 1 - exp2(-2*d*d);
					return d;
				}

				void main() {
					float d1 = min(min(gTriDistance.x, gTriDistance.y), gTriDistance.z);
					float step = smoothstep(0, fwidth(d1), d1);
    				color = step * gVertexColor + (1 - step) * gBorderColor;
				}""", GL_FRAGMENT_SHADER))
		
		self.vao = glGenVertexArrays(1)

	def getCheckData(self, checkList):
		out = set()

		while checkList >= 0x80000000:
			checkData = self.dolphin.read_uint32(checkList + 0x8)
			if checkData >= 0x80000000:
				out.add(checkData)
			checkList = self.dolphin.read_uint32(checkList + 0x4)

		return out

	def makeCylinder(self, x, y, z, h, r, n, pt = PlaneType.HITBOX):
		"""Return a list of triangles approximating a cylinder oriented along the Y axis.

		x, y, z -- coordinates of the center of the cylinder's base
		h -- height of the cylinder
		r -- radius of the cylinder
		n -- number of sides of the polygon used in place of the circular faces
		"""
		
		result = []
		y1 = y + h # height

		## loop each side
		th = 0
		for i in range(1, n + 1):
			th0, th = th, tau * i / n
			x0 = x + r * cos(th0)
			z0 = z + r * sin(th0)
			x1 = x + r * cos(th)
			z1 = z + r * sin(th)
			result += [
				# bottom and top triangle
				[x, y, z, pt], [x1, y, z1, pt], [x0, y, z0, pt],
				[x, y1, z, pt], [x1, y1, z1, pt], [x0, y1, z0, pt],
				# side rectangle
				[x0, y, z0, pt], [x1, y1, z1, pt], [x1, y, z1, pt],
				[x1, y1, z1, pt], [x0, y, z0, pt], [x0, y1, z0, pt],
			]

			return result
	
	def paintGL(self) -> None:
		try: # prevent crashing on level transition
			self._paintGL()
		except:
			traceback.print_exc()
	
	def _paintGL(self) -> None:
		if self.gpCamera == 0 or self.gpMapCollisionData == 0:
			return

		glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

		camera = self.dolphin.read_uint32(self.gpCamera)
		if camera == 0:
			return

		projMat = pyrr.matrix44.create_perspective_projection_matrix(self.dolphin.read_float(camera + 0x48), self.aspect,
				self.dolphin.read_float(camera + 0x28), self.dolphin.read_float(camera + 0x2C))
		viewMat = pyrr.matrix44.create_look_at(
				[self.dolphin.read_float(camera + 0x124), self.dolphin.read_float(camera + 0x128), self.dolphin.read_float(camera + 0x12C)],
				[self.dolphin.read_float(camera + 0x148), self.dolphin.read_float(camera + 0x14C), self.dolphin.read_float(camera + 0x150)],
				[self.dolphin.read_float(camera + 0x30), self.dolphin.read_float(camera + 0x34), self.dolphin.read_float(camera + 0x38)])

		floors = set()
		roofs = set()
		walls = set()
		cubes = set()
		
		mapColData = self.dolphin.read_uint32(self.gpMapCollisionData)
		if mapColData == 0:
			return
		
		checkListCount = self.dolphin.read_uint32(mapColData + 0x10)
		checkLists1 = self.dolphin.read_uint32(mapColData + 0x14)
		checkLists2 = self.dolphin.read_uint32(mapColData + 0x18)

		for i in range(checkListCount):
			if checkLists1 != 0:
				floors |= self.getCheckData(self.dolphin.read_uint32(checkLists1 + 0x24 * i + 0x4))
				roofs |= self.getCheckData(self.dolphin.read_uint32(checkLists1 + 0x24 * i + 0x10))
				walls |= self.getCheckData(self.dolphin.read_uint32(checkLists1 + 0x24 * i + 0x1C))
			
			if checkLists2 != 0:
				floors |= self.getCheckData(self.dolphin.read_uint32(checkLists2 + 0x24 * i + 0x4))
				roofs |= self.getCheckData(self.dolphin.read_uint32(checkLists2 + 0x24 * i + 0x10))
				walls |= self.getCheckData(self.dolphin.read_uint32(checkLists2 + 0x24 * i + 0x1C))
		
		for i in range(3):
			cube = self.dolphin.read_uint32(self.gpCubeFastA + 4 * i)
			if cube < 0x80000000:
				continue
			
			length = self.dolphin.read_uint8(cube + 0x10)
			infoptr = self.dolphin.read_uint32(cube + 0x14)
			if infoptr < 0x80000000:
				continue

			info = self.dolphin.read_uint32(infoptr + 0x10)
			if info < 0x80000000:
				continue

			for j in range(length):
				cubes.add(self.dolphin.read_uint32(info + 4 * j))
		
		buffer = []

		# Mario's hitbox
		ptrMario = self.dolphin.read_uint32(self.gpMarioOriginal)
		x, y, z = (self.dolphin.read_float(ptrMario+i) for i in (0x10, 0x14, 0x18))
		buffer += self.makeCylinder(x, y, z, 160, 50, 12)

		for f in floors:
			ptype = PlaneType.WATER if self.dolphin.read_uint16(f) in [0x100, 0x101, 0x102, 0x103, 0x104, 0x105, 0x4104] else PlaneType.FLOOR
			buffer += [
				[self.dolphin.read_float(f + 0x10), self.dolphin.read_float(f + 0x14), self.dolphin.read_float(f + 0x18), ptype],
				[self.dolphin.read_float(f + 0x1C), self.dolphin.read_float(f + 0x20), self.dolphin.read_float(f + 0x24), ptype],
				[self.dolphin.read_float(f + 0x28), self.dolphin.read_float(f + 0x2C), self.dolphin.read_float(f + 0x30), ptype]
			]

		for r in roofs:
			buffer += [
				[self.dolphin.read_float(r + 0x10), self.dolphin.read_float(r + 0x14), self.dolphin.read_float(r + 0x18), PlaneType.ROOF],
				[self.dolphin.read_float(r + 0x1C), self.dolphin.read_float(r + 0x20), self.dolphin.read_float(r + 0x24), PlaneType.ROOF],
				[self.dolphin.read_float(r + 0x28), self.dolphin.read_float(r + 0x2C), self.dolphin.read_float(r + 0x30), PlaneType.ROOF]
			]

		for w in walls:
			ptype = PlaneType.WALLX if self.dolphin.read_uint16(w + 0x4) & 0x8 else PlaneType.WALLZ
			buffer += [
				[self.dolphin.read_float(w + 0x10), self.dolphin.read_float(w + 0x14), self.dolphin.read_float(w + 0x18), ptype],
				[self.dolphin.read_float(w + 0x1C), self.dolphin.read_float(w + 0x20), self.dolphin.read_float(w + 0x24), ptype],
				[self.dolphin.read_float(w + 0x28), self.dolphin.read_float(w + 0x2C), self.dolphin.read_float(w + 0x30), ptype]
			]
		
		for c in cubes:
			cx, cy, cz = self.dolphin.read_float(c + 0xC), self.dolphin.read_float(c + 0x10), self.dolphin.read_float(c + 0x14)
			dx, dy, dz = self.dolphin.read_float(c + 0x24), self.dolphin.read_float(c + 0x28), self.dolphin.read_float(c + 0x2C)

			v = [
				[cx - .5 * dx, cy, cz - .5 * dz, PlaneType.CUBE], [cx - .5 * dx, cy + dy, cz - .5 * dz, PlaneType.CUBE],
				[cx - .5 * dx, cy, cz + .5 * dz, PlaneType.CUBE], [cx - .5 * dx, cy + dy, cz + .5 * dz, PlaneType.CUBE],
				[cx + .5 * dx, cy, cz + .5 * dz, PlaneType.CUBE], [cx + .5 * dx, cy + dy, cz + .5 * dz, PlaneType.CUBE],
				[cx + .5 * dx, cy, cz - .5 * dz, PlaneType.CUBE], [cx + .5 * dx, cy + dy, cz - .5 * dz, PlaneType.CUBE]
			]

			buffer += [
				v[0], v[1], v[2], v[1], v[3], v[2], # inward -x
				v[2], v[3], v[4], v[3], v[5], v[4], # inward +z
				v[4], v[5], v[6], v[5], v[7], v[6], # inward +x
				v[6], v[7], v[0], v[7], v[1], v[0], # inward -z
				v[0], v[2], v[4], v[0], v[4], v[6], # inward -y
				v[1], v[5], v[3], v[1], v[7], v[5], # inward +y
				v[0], v[2], v[1], v[1], v[2], v[3], # outward -x
				v[2], v[4], v[3], v[3], v[4], v[5], # outward +z
				v[4], v[6], v[5], v[5], v[6], v[7], # outward +x
				v[6], v[0], v[7], v[7], v[0], v[1], # outward -z
				v[0], v[4], v[2], v[0], v[6], v[4], # outward -y
				v[1], v[3], v[5], v[1], v[5], v[7], # outward +y
			]

		glUseProgram(self.shader)

		glUniformMatrix4fv(glGetUniformLocation(self.shader, 'projMat'), 1, False, projMat)
		glUniformMatrix4fv(glGetUniformLocation(self.shader, 'viewMat'), 1, False, viewMat)

		glBindVertexArray(self.vao)
		vertexBuffer = vbo.VBO(array(buffer, 'f'))
		try:
			vertexBuffer.bind()
			try:
				glEnableVertexAttribArray(0)
				glVertexAttribPointer(0, 3, GL_FLOAT, False, 16, vertexBuffer)
				glEnableVertexAttribArray(1)
				glVertexAttribPointer(1, 1, GL_FLOAT, False, 16, vertexBuffer + 12)
				glDrawArrays(GL_TRIANGLES, 0, len(buffer))
			finally:
				vertexBuffer.unbind()
		finally:
			glBindVertexArray(0)
			glUseProgram(0)
	
	def resizeGL(self, w: int, h: int) -> None:
		self.width = w
		self.height = h or 1
		self.aspect = self.width / self.height
		glViewport(0, 0, self.width, self.height)

def connect():
	if not dolphin.find_dolphin():
		status.showMessage('Dolphin not found')
		return

	if not dolphin.init_shared_memory():
		status.showMessage('MEM1 not found')
		return

	if dolphin.read_ram(0, 3).tobytes() != b'GMS':
		status.showMessage('Current game is not Sunshine')
		return

	viewer.gpCamera, viewer.gpCubeFastA, viewer.gpMapCollisionData, viewer.gpMarioOriginal = {
		0x23: (0x8040B370, 0x8040B3B0, 0x8040A578, 0x8040A378), # JP 1.0
		0xA3: (0x8040D0A8, 0x8040D0E8, 0x8040DEA0, 0x8040E0E8), # NA / KOR
		0x41: (0x80404808, 0x80404848, 0x80405568, 0x804057B0), # PAL
		0x80: (0x803FFA38, 0x803FFA78, 0x803FED40, 0x803FEF88), # JP 1.1
		0x4D: (0x80401D08, 0x80401D48, 0x80402A68, 0x80402CB0), # 3DAS
	}.get(dolphin.read_uint8(0x80365DDD))

	status.showMessage('Ready')

if __name__ == '__main__':
	dolphin = Dolphin()

	app = QtWidgets.QApplication(sys.argv)

	window = QtWidgets.QWidget()
	layout = QtWidgets.QVBoxLayout(window)
	viewer = CollisionViewer(dolphin)
	button = QtWidgets.QPushButton('Connect to Dolphin')
	status = QtWidgets.QStatusBar()

	button.clicked.connect(connect)

	layout.addWidget(viewer)
	layout.addWidget(button)
	layout.addWidget(status)
	layout.setStretch(0, 1)

	window.setWindowTitle('Super Mario Sunshine Live Collision Viewer')
	window.resize(800, 600)
	window.show()

	try:
		sys.exit(app.exec())
	except SystemExit:
		pass
