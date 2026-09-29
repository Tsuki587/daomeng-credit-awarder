import unittest
from unittest.mock import Mock

from daomeng.config import Student
from daomeng.device_controller import DeviceController
from daomeng.selectors import SELECTORS


class SearchStudentTests(unittest.TestCase):
    def setUp(self):
        self.student = Student("12345678901", "学生甲", 1.0, "未处理")
        self.search = Mock()
        self.row = Mock()
        self.loading = Mock()
        self.empty = Mock()
        self.other = Mock()
        self.device = Mock()
        self.device.side_effect = self.select
        self.controller = DeviceController.__new__(DeviceController)
        self.controller.device = self.device
        self.controller._logger = Mock()

    def select(self, **selector):
        if selector == SELECTORS["人员搜索框"]:
            return self.search
        if selector == {**SELECTORS["人员信息"], "text": self.student.name}:
            return self.row
        if selector == SELECTORS["加载"]:
            return self.loading
        if selector == SELECTORS["无结果"]:
            return self.empty
        if selector == SELECTORS["人员信息"]:
            return self.other
        raise AssertionError(selector)

    def test_old_empty_state_does_not_end_current_search(self):
        self.empty.exists = True
        self.row.wait.return_value = True

        result = self.controller._search_student(self.student)

        self.assertIs(result, self.row)
        self.assertEqual(self.student.status, "未处理")
        self.search.set_text.assert_called_once_with(self.student.student_id)
        self.device.press.assert_called_once_with("enter")

    def test_old_name_does_not_end_next_search(self):
        self.row.wait.side_effect = [False, True]
        self.other.exists = True
        self.other.get_text.return_value = "上一位学生"

        result = self.controller._search_student(self.student)

        self.assertIs(result, self.row)
        self.assertEqual(self.search.set_text.call_count, 2)
        self.assertEqual(self.device.press.call_count, 2)
        self.other.get_text.assert_not_called()

    def test_two_empty_searches_need_review(self):
        self.row.wait.return_value = False
        self.empty.exists = True

        result = self.controller._search_student(self.student)

        self.assertIsNone(result)
        self.assertEqual(self.student.status, "待核对（两次搜索无结果）")

    def test_two_mismatches_need_review(self):
        self.row.wait.return_value = False
        self.empty.exists = False
        self.other.exists = True
        self.other.get_text.return_value = "上一位学生"

        result = self.controller._search_student(self.student)

        self.assertIsNone(result)
        self.assertIn("待核对（姓名不符", self.student.status)

    def test_unconfirmed_result_never_reaches_award_click(self):
        self.controller._score = Mock(return_value=self.student.points)
        self.controller._config = Mock(click_other_tab=False)
        self.controller._search_student = Mock(return_value=None)
        self.student.status = "待核对（搜索结果未确认）"

        result = self.controller.award_points(self.student)

        self.assertIs(result, self.student)
        self.device.assert_not_called()


if __name__ == "__main__":
    unittest.main()
