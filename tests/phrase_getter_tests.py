import os
import unittest
import shutil
from ..src.phrase_getter import phrase_getter
from ..src.phrase_getter import visemes

TEST_FILE_PATH = "./test_files/

class PhraseGetterTest(unittest.TestCase):
    def test_phrase_getter(self):
        shutil.rmtree(TEST_FILE_PATH)
        os.mkdir(TEST_FILE_PATH)
        phrase_getter.get('fun', 'dgilbert418', output_directory=TEST_FILE_PATH)

        num_files = len(os.listdir(TEST_FILE_PATH + "clips/fun/"))
        print(num_files)
        self.assertTrue(num_files >= 4)  # add assertion here


if __name__ == '__main__':
    unittest.main()
