import sys, pyrr

from PyQt5 import QtCore
from PyQt5 import QtGui
from PyQt5 import QtWidgets

from OpenGL.GL import *
from OpenGL.GLUT import *
from OpenGL.GLU import *
from OpenGL.arrays import vbo
from OpenGL.GL import shaders

from numpy import array

from memorylib import Dolphin

class CollisionViewer(QtWidgets.QOpenGLWidget):
	gpCamera = 0
	gpMapCollisionData = 0

	def __init__(self, dolphin: Dolphin, parent=None):
		self.dolphin = dolphin
		self.parent = parent
		QtWidgets.QOpenGLWidget.__init__(self, parent)
		self.resize(800, 600)
		self.frameSwapped.connect(self.update)

	def initializeGL(self) -> None:
		glEnable(GL_DEPTH_TEST)
		glEnable(GL_CULL_FACE)
		glClearColor(0.7, 0.7, 1.0, 0.0)

		self.shader = shaders.compileProgram(
				shaders.compileShader("""#version 330 core
				uniform mat4 projMat;
				uniform mat4 viewMat;

				layout (location = 0) in vec3 position;
				layout (location = 1) in float type;

				out vec4 vVertexColor;

				void main() {
					gl_Position = projMat * viewMat * vec4(position, 1.0);
					
					if (type == 0) {
						vVertexColor = vec4(0, 0, 1, 1);
					} else if (type == 1) {
						vVertexColor = vec4(1, 0, 0, 1);
					} else if (type == 2) {
						vVertexColor = vec4(0, 1, 0, 1);
					} else if (type == 3) {
						vVertexColor = vec4(0, 0.5, 0, 1);
					} else {
						vVertexColor = vec4(0.5, 0.5, 0.5, 1);
					}
				}""", GL_VERTEX_SHADER),
				shaders.compileShader("""#version 330 core
				layout(triangles) in;
				layout(triangle_strip, max_vertices = 3) out;

				in vec4 vVertexColor[3];
				out vec3 gTriDistance;
				out float gTriSize;
				out vec4 gVertexColor;

				void main() {
					gTriSize = max(max(distance(gl_in[0].gl_Position, gl_in[1].gl_Position),
							distance(gl_in[0].gl_Position, gl_in[2].gl_Position)),
							distance(gl_in[1].gl_Position, gl_in[2].gl_Position));

					gTriDistance = vec3(1, 0, 0);
					gVertexColor = vVertexColor[0];
					gl_Position = gl_in[0].gl_Position;
					EmitVertex();

					gTriDistance = vec3(0, 1, 0);
					gVertexColor = vVertexColor[1];
					gl_Position = gl_in[1].gl_Position;
					EmitVertex();

					gTriDistance = vec3(0, 0, 1);
					gVertexColor = vVertexColor[2];
					gl_Position = gl_in[2].gl_Position;
					EmitVertex();

					EndPrimitive();
				}""", GL_GEOMETRY_SHADER),
				shaders.compileShader("""#version 330 core
				in vec3 gTriDistance;
				in float gTriSize;
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
    				color = smoothstep(0, fwidth(d1), d1) * gVertexColor;
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

	
	def paintGL(self) -> None:
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
		
		mapColData = self.dolphin.read_uint32(self.gpMapCollisionData)
		if mapColData == 0:
			return
		
		checkListCount = self.dolphin.read_uint32(mapColData + 0x10)
		checkLists1 = self.dolphin.read_uint32(mapColData + 0x14)
		checkLists2 = self.dolphin.read_uint32(mapColData + 0x18)

		floors = set()
		roofs = set()
		walls = set()

		for i in range(checkListCount):
			if checkLists1 != 0:
				floors |= self.getCheckData(self.dolphin.read_uint32(checkLists1 + 0x24 * i + 0x4))
				roofs |= self.getCheckData(self.dolphin.read_uint32(checkLists1 + 0x24 * i + 0x10))
				walls |= self.getCheckData(self.dolphin.read_uint32(checkLists1 + 0x24 * i + 0x1C))
			
			if checkLists2 != 0:
				floors |= self.getCheckData(self.dolphin.read_uint32(checkLists2 + 0x24 * i + 0x4))
				roofs |= self.getCheckData(self.dolphin.read_uint32(checkLists2 + 0x24 * i + 0x10))
				walls |= self.getCheckData(self.dolphin.read_uint32(checkLists2 + 0x24 * i + 0x1C))
		
		buffer = []

		for f in floors:
			buffer += [
				[self.dolphin.read_float(f + 0x10), self.dolphin.read_float(f + 0x14), self.dolphin.read_float(f + 0x18), 0],
				[self.dolphin.read_float(f + 0x1C), self.dolphin.read_float(f + 0x20), self.dolphin.read_float(f + 0x24), 0],
				[self.dolphin.read_float(f + 0x28), self.dolphin.read_float(f + 0x2C), self.dolphin.read_float(f + 0x30), 0]
			]

		for r in roofs:
			buffer += [
				[self.dolphin.read_float(r + 0x10), self.dolphin.read_float(r + 0x14), self.dolphin.read_float(r + 0x18), 1],
				[self.dolphin.read_float(r + 0x1C), self.dolphin.read_float(r + 0x20), self.dolphin.read_float(r + 0x24), 1],
				[self.dolphin.read_float(r + 0x28), self.dolphin.read_float(r + 0x2C), self.dolphin.read_float(r + 0x30), 1]
			]

		for w in walls:
			proj = 3 if self.dolphin.read_uint16(w + 0x4) & 0x8 else 2
			buffer += [
				[self.dolphin.read_float(w + 0x10), self.dolphin.read_float(w + 0x14), self.dolphin.read_float(w + 0x18), proj],
				[self.dolphin.read_float(w + 0x1C), self.dolphin.read_float(w + 0x20), self.dolphin.read_float(w + 0x24), proj],
				[self.dolphin.read_float(w + 0x28), self.dolphin.read_float(w + 0x2C), self.dolphin.read_float(w + 0x30), proj]
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
	
	viewer.gpCamera, viewer.gpMapCollisionData = {
		0x23: (0x8040B370, 0x8040A578), # JP 1.0
		0xA3: (0x8040D0A8, 0x8040DEA0), # NA / KOR
		0x41: (0x80404808, 0x80405568), # PAL
		0x80: (0x803FFA38, 0x803FED40), # JP 1.1
		0x4D: (0x80401D08, 0x80402A68), # 3DAS
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