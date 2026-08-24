"""
校园信息查询 MCP Server

提供课程搜索、教师信息、教室查询、课表获取等校园信息服务。
使用模拟数据，数据结构模拟真实校园信息场景。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schema import ToolSchema, make_tool_schema
from ..server import MCPServer


# ---------------------------------------------------------------------------
# 模拟数据
# ---------------------------------------------------------------------------

# 课程数据
_COURSES: List[Dict[str, Any]] = [
    {
        "id": "CS101",
        "name": "计算机科学导论",
        "department": "计算机科学与技术学院",
        "teacher": "张明远",
        "credits": 3,
        "semester": "2025-2026-1",
        "schedule": "周一 8:00-9:40, 周三 10:00-11:40",
        "classroom": "教一楼 301",
        "capacity": 120,
        "enrolled": 98,
        "description": "介绍计算机科学的基本概念、历史发展和应用领域，涵盖算法、数据结构、操作系统等基础知识。",
    },
    {
        "id": "CS202",
        "name": "数据结构与算法",
        "department": "计算机科学与技术学院",
        "teacher": "李华",
        "credits": 4,
        "semester": "2025-2026-1",
        "schedule": "周二 14:00-15:40, 周四 14:00-15:40",
        "classroom": "教一楼 405",
        "capacity": 100,
        "enrolled": 95,
        "description": "系统学习线性表、树、图等数据结构及其相关算法，培养算法设计与分析能力。",
    },
    {
        "id": "CS301",
        "name": "操作系统",
        "department": "计算机科学与技术学院",
        "teacher": "王建国",
        "credits": 4,
        "semester": "2025-2026-1",
        "schedule": "周一 14:00-15:40, 周五 8:00-9:40",
        "classroom": "教二楼 201",
        "capacity": 90,
        "enrolled": 85,
        "description": "深入讲解进程管理、内存管理、文件系统、I/O系统等操作系统核心概念与实现原理。",
    },
    {
        "id": "CS302",
        "name": "计算机网络",
        "department": "计算机科学与技术学院",
        "teacher": "赵雪梅",
        "credits": 3,
        "semester": "2025-2026-1",
        "schedule": "周三 14:00-15:40, 周五 10:00-11:40",
        "classroom": "教二楼 305",
        "capacity": 100,
        "enrolled": 78,
        "description": "学习计算机网络体系结构、TCP/IP协议栈、路由算法、网络安全等核心知识。",
    },
    {
        "id": "AI201",
        "name": "人工智能基础",
        "department": "人工智能学院",
        "teacher": "陈博文",
        "credits": 3,
        "semester": "2025-2026-1",
        "schedule": "周二 10:00-11:40, 周四 8:00-9:40",
        "classroom": "教三楼 102",
        "capacity": 120,
        "enrolled": 115,
        "description": "介绍人工智能的基本概念、搜索算法、知识表示、机器学习基础等内容。",
    },
    {
        "id": "AI302",
        "name": "深度学习",
        "department": "人工智能学院",
        "teacher": "陈博文",
        "credits": 4,
        "semester": "2025-2026-1",
        "schedule": "周一 16:00-17:40, 周三 16:00-17:40",
        "classroom": "教三楼 201",
        "capacity": 80,
        "enrolled": 80,
        "description": "系统学习深度神经网络、CNN、RNN、Transformer等模型及其在计算机视觉、自然语言处理中的应用。",
    },
    {
        "id": "SE201",
        "name": "软件工程",
        "department": "软件学院",
        "teacher": "刘志强",
        "credits": 3,
        "semester": "2025-2026-1",
        "schedule": "周一 10:00-11:40, 周四 10:00-11:40",
        "classroom": "教四楼 101",
        "capacity": 100,
        "enrolled": 72,
        "description": "学习软件生命周期、需求分析、系统设计、测试、项目管理等软件工程核心方法。",
    },
    {
        "id": "SE302",
        "name": "Web 全栈开发",
        "department": "软件学院",
        "teacher": "刘志强",
        "credits": 3,
        "semester": "2025-2026-1",
        "schedule": "周二 16:00-17:40, 周五 14:00-15:40",
        "classroom": "教四楼 205",
        "capacity": 80,
        "enrolled": 76,
        "description": "前端React/Vue框架、后端Node.js/Python、数据库设计、API开发等全栈技术实战。",
    },
    {
        "id": "MATH101",
        "name": "高等数学（上）",
        "department": "数学与统计学院",
        "teacher": "杨秀英",
        "credits": 5,
        "semester": "2025-2026-1",
        "schedule": "周一 8:00-9:40, 周三 8:00-9:40, 周五 8:00-9:40",
        "classroom": "教五楼 大礼堂",
        "capacity": 200,
        "enrolled": 180,
        "description": "极限、导数、积分、微分方程等基础数学知识，为后续专业课程奠定数学基础。",
    },
    {
        "id": "EE201",
        "name": "数字电路",
        "department": "电子工程学院",
        "teacher": "周德明",
        "credits": 3,
        "semester": "2025-2026-1",
        "schedule": "周二 8:00-9:40, 周四 14:00-15:40",
        "classroom": "教六楼 实验室A",
        "capacity": 60,
        "enrolled": 55,
        "description": "逻辑门电路、组合逻辑、时序逻辑、触发器、寄存器等数字电路基础知识。",
    },
]

# 教师数据
_TEACHERS: List[Dict[str, Any]] = [
    {
        "id": "T001",
        "name": "张明远",
        "department": "计算机科学与技术学院",
        "title": "教授",
        "email": "zhangmy@campus.edu.cn",
        "office": "教一楼 502",
        "research": ["分布式系统", "云计算", "大数据处理"],
        "courses": ["CS101"],
        "office_hours": "周三 14:00-16:00",
    },
    {
        "id": "T002",
        "name": "李华",
        "department": "计算机科学与技术学院",
        "title": "副教授",
        "email": "lihua@campus.edu.cn",
        "office": "教一楼 408",
        "research": ["算法设计与分析", "图论", "组合优化"],
        "courses": ["CS202"],
        "office_hours": "周二 14:00-16:00",
    },
    {
        "id": "T003",
        "name": "王建国",
        "department": "计算机科学与技术学院",
        "title": "教授",
        "email": "wangjg@campus.edu.cn",
        "office": "教二楼 301",
        "research": ["操作系统", "系统安全", "虚拟化技术"],
        "courses": ["CS301"],
        "office_hours": "周四 10:00-12:00",
    },
    {
        "id": "T004",
        "name": "赵雪梅",
        "department": "计算机科学与技术学院",
        "title": "讲师",
        "email": "zhaoxm@campus.edu.cn",
        "office": "教二楼 310",
        "research": ["计算机网络", "SDN", "网络测量"],
        "courses": ["CS302"],
        "office_hours": "周五 14:00-16:00",
    },
    {
        "id": "T005",
        "name": "陈博文",
        "department": "人工智能学院",
        "title": "教授",
        "email": "chenbw@campus.edu.cn",
        "office": "教三楼 501",
        "research": ["深度学习", "自然语言处理", "计算机视觉"],
        "courses": ["AI201", "AI302"],
        "office_hours": "周一 14:00-16:00",
    },
    {
        "id": "T006",
        "name": "刘志强",
        "department": "软件学院",
        "title": "副教授",
        "email": "liuzq@campus.edu.cn",
        "office": "教四楼 302",
        "research": ["软件工程", "敏捷开发", "DevOps"],
        "courses": ["SE201", "SE302"],
        "office_hours": "周三 10:00-12:00",
    },
    {
        "id": "T007",
        "name": "杨秀英",
        "department": "数学与统计学院",
        "title": "教授",
        "email": "yangxy@campus.edu.cn",
        "office": "教五楼 201",
        "research": ["偏微分方程", "数值分析", "数学建模"],
        "courses": ["MATH101"],
        "office_hours": "周二 10:00-12:00",
    },
    {
        "id": "T008",
        "name": "周德明",
        "department": "电子工程学院",
        "title": "讲师",
        "email": "zhoudm@campus.edu.cn",
        "office": "教六楼 105",
        "research": ["数字电路设计", "FPGA", "嵌入式系统"],
        "courses": ["EE201"],
        "office_hours": "周四 14:00-16:00",
    },
]

# 教室数据
_CLASSROOMS: List[Dict[str, Any]] = [
    {
        "building": "教一楼",
        "room_number": "301",
        "type": "多媒体教室",
        "capacity": 120,
        "equipment": ["投影仪", "电脑", "音响", "空调"],
        "status": "available",
        "floor": 3,
    },
    {
        "building": "教一楼",
        "room_number": "405",
        "type": "多媒体教室",
        "capacity": 100,
        "equipment": ["投影仪", "电脑", "音响", "空调"],
        "status": "available",
        "floor": 4,
    },
    {
        "building": "教二楼",
        "room_number": "201",
        "type": "多媒体教室",
        "capacity": 90,
        "equipment": ["投影仪", "电脑", "音响"],
        "status": "available",
        "floor": 2,
    },
    {
        "building": "教二楼",
        "room_number": "305",
        "type": "多媒体教室",
        "capacity": 100,
        "equipment": ["投影仪", "电脑", "音响", "空调"],
        "status": "available",
        "floor": 3,
    },
    {
        "building": "教三楼",
        "room_number": "102",
        "type": "阶梯教室",
        "capacity": 120,
        "equipment": ["投影仪", "电脑", "音响", "空调"],
        "status": "available",
        "floor": 1,
    },
    {
        "building": "教三楼",
        "room_number": "201",
        "type": "多媒体教室",
        "capacity": 80,
        "equipment": ["投影仪", "电脑", "音响", "空调"],
        "status": "occupied",
        "floor": 2,
    },
    {
        "building": "教四楼",
        "room_number": "101",
        "type": "多媒体教室",
        "capacity": 100,
        "equipment": ["投影仪", "电脑", "音响"],
        "status": "available",
        "floor": 1,
    },
    {
        "building": "教四楼",
        "room_number": "205",
        "type": "计算机房",
        "capacity": 80,
        "equipment": ["投影仪", "电脑x80", "交换机", "空调"],
        "status": "available",
        "floor": 2,
    },
    {
        "building": "教五楼",
        "room_number": "大礼堂",
        "type": "大礼堂",
        "capacity": 200,
        "equipment": ["投影仪", "电脑", "音响", "空调", "录播系统"],
        "status": "available",
        "floor": 1,
    },
    {
        "building": "教六楼",
        "room_number": "实验室A",
        "type": "实验室",
        "capacity": 60,
        "equipment": ["示波器", "信号发生器", "电源", "实验台x30"],
        "status": "available",
        "floor": 1,
    },
]

# 学生课表数据
_STUDENT_SCHEDULES: Dict[str, List[Dict[str, Any]]] = {
    "2024010001": [
        {"course_id": "CS101", "semester": "2025-2026-1", "type": "必修", "grade": None},
        {"course_id": "CS202", "semester": "2025-2026-1", "type": "必修", "grade": None},
        {"course_id": "MATH101", "semester": "2025-2026-1", "type": "必修", "grade": None},
        {"course_id": "SE201", "semester": "2025-2026-1", "type": "选修", "grade": None},
    ],
    "2024010002": [
        {"course_id": "AI201", "semester": "2025-2026-1", "type": "必修", "grade": None},
        {"course_id": "AI302", "semester": "2025-2026-1", "type": "必修", "grade": None},
        {"course_id": "CS301", "semester": "2025-2026-1", "type": "选修", "grade": None},
        {"course_id": "CS302", "semester": "2025-2026-1", "type": "选修", "grade": None},
    ],
    "2024010003": [
        {"course_id": "SE302", "semester": "2025-2026-1", "type": "必修", "grade": None},
        {"course_id": "CS202", "semester": "2025-2026-1", "type": "必修", "grade": None},
        {"course_id": "EE201", "semester": "2025-2026-1", "type": "选修", "grade": None},
    ],
}


# ---------------------------------------------------------------------------
# CampusInfoServer
# ---------------------------------------------------------------------------

class CampusInfoServer(MCPServer):
    """校园信息查询 MCP Server。

    提供课程搜索、教师信息、教室查询、课表获取等校园信息服务。
    """

    def __init__(self) -> None:
        super().__init__(
            name="campus-info",
            version="1.0.0",
            description="校园信息查询服务，支持课程搜索、教师信息、教室查询、课表获取",
            default_timeout=10.0,
        )
        self._register_all_tools()

    def _register_all_tools(self) -> None:
        """注册所有工具。"""

        # --- search_courses ---
        self.register_tool(
            schema=make_tool_schema(
                name="search_courses",
                description="搜索课程信息，支持按关键词和学院筛选。返回课程名称、教师、学分、时间地点等详细信息。",
                parameters={
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "搜索关键词，匹配课程名称和描述",
                        },
                        "department": {
                            "type": "string",
                            "description": "学院名称（可选），如'计算机科学与技术学院'、'人工智能学院'等",
                        },
                    },
                    "required": ["keyword"],
                },
            ),
            handler=self._search_courses,
            timeout=5.0,
        )

        # --- get_teacher_info ---
        self.register_tool(
            schema=make_tool_schema(
                name="get_teacher_info",
                description="获取教师详细信息，包括职称、研究方向、办公地点、办公时间、所授课程等。",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "教师姓名",
                        },
                    },
                    "required": ["name"],
                },
            ),
            handler=self._get_teacher_info,
            timeout=5.0,
        )

        # --- query_classroom ---
        self.register_tool(
            schema=make_tool_schema(
                name="query_classroom",
                description="查询教室信息，包括类型、容量、设备、当前状态等。",
                parameters={
                    "type": "object",
                    "properties": {
                        "building": {
                            "type": "string",
                            "description": "教学楼名称，如'教一楼'、'教二楼'等",
                        },
                        "room_number": {
                            "type": "string",
                            "description": "教室编号",
                        },
                    },
                    "required": ["building", "room_number"],
                },
            ),
            handler=self._query_classroom,
            timeout=5.0,
        )

        # --- get_schedule ---
        self.register_tool(
            schema=make_tool_schema(
                name="get_schedule",
                description="获取学生课表信息，返回指定学期所有课程及上课时间地点。",
                parameters={
                    "type": "object",
                    "properties": {
                        "student_id": {
                            "type": "string",
                            "description": "学号",
                        },
                        "semester": {
                            "type": "string",
                            "description": "学期，格式如'2025-2026-1'",
                            "default": "2025-2026-1",
                        },
                    },
                    "required": ["student_id"],
                },
            ),
            handler=self._get_schedule,
            timeout=5.0,
        )

        # --- list_departments ---
        self.register_tool(
            schema=make_tool_schema(
                name="list_departments",
                description="列出所有学院及其开设课程数量。",
                parameters={
                    "type": "object",
                    "properties": {},
                },
            ),
            handler=self._list_departments,
            timeout=5.0,
        )

    # ------------------------------------------------------------------
    # 工具实现
    # ------------------------------------------------------------------

    def _search_courses(
        self, keyword: str, department: Optional[str] = None
    ) -> Dict[str, Any]:
        """搜索课程。"""
        keyword_lower = keyword.lower()
        results = []
        for course in _COURSES:
            name_match = keyword_lower in course["name"].lower()
            desc_match = keyword_lower in course.get("description", "").lower()
            teacher_match = keyword_lower in course["teacher"].lower()
            if not (name_match or desc_match or teacher_match):
                continue
            if department and department not in course["department"]:
                continue
            results.append(course)

        return {
            "total": len(results),
            "keyword": keyword,
            "department_filter": department,
            "courses": results,
        }

    def _get_teacher_info(self, name: str) -> Dict[str, Any]:
        """获取教师信息。"""
        for teacher in _TEACHERS:
            if teacher["name"] == name:
                return {
                    "found": True,
                    "teacher": teacher,
                }
        return {
            "found": False,
            "teacher": None,
            "message": f"未找到教师: {name}",
        }

    def _query_classroom(
        self, building: str, room_number: str
    ) -> Dict[str, Any]:
        """查询教室信息。"""
        for room in _CLASSROOMS:
            if room["building"] == building and room["room_number"] == room_number:
                # 查找当前在该教室上课的课程
                current_courses = []
                for course in _COURSES:
                    cls = course.get("classroom", "")
                    if building in cls and room_number in cls:
                        current_courses.append({
                            "course_id": course["id"],
                            "name": course["name"],
                            "schedule": course["schedule"],
                        })
                return {
                    "found": True,
                    "classroom": room,
                    "current_courses": current_courses,
                }
        return {
            "found": False,
            "classroom": None,
            "message": f"未找到教室: {building} {room_number}",
        }

    def _get_schedule(
        self, student_id: str, semester: str = "2025-2026-1"
    ) -> Dict[str, Any]:
        """获取课表。"""
        enrolled = _STUDENT_SCHEDULES.get(student_id)
        if not enrolled:
            return {
                "found": False,
                "student_id": student_id,
                "message": f"未找到学号为 {student_id} 的学生课表",
            }

        schedule_detail = []
        for entry in enrolled:
            if entry["semester"] != semester:
                continue
            course = next(
                (c for c in _COURSES if c["id"] == entry["course_id"]), None
            )
            if course:
                schedule_detail.append({
                    **entry,
                    "course_name": course["name"],
                    "teacher": course["teacher"],
                    "schedule": course["schedule"],
                    "classroom": course["classroom"],
                    "credits": course["credits"],
                })

        return {
            "found": True,
            "student_id": student_id,
            "semester": semester,
            "total_courses": len(schedule_detail),
            "schedule": schedule_detail,
        }

    def _list_departments(self) -> Dict[str, Any]:
        """列出所有学院。"""
        dept_map: Dict[str, int] = {}
        for course in _COURSES:
            dept = course["department"]
            dept_map[dept] = dept_map.get(dept, 0) + 1

        departments = [
            {"name": name, "course_count": count}
            for name, count in sorted(dept_map.items(), key=lambda x: x[1], reverse=True)
        ]
        return {
            "total": len(departments),
            "departments": departments,
        }