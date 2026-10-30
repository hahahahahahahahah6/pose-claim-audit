import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pose_claim_audit.audit import audit, claims, evidence, matches
from pose_claim_audit.phrases import POSE, NOPOSE

ROOT = Path(__file__).resolve().parents[1]


class ClaimsTests(unittest.TestCase):
    def test_fences(self):
        for fence in ('```', '~~~', '   ````'):
            self.assertEqual(claims(fence+'\nsupports pose estimation\n'+fence), (False, False))

    def test_inline(self):
        self.assertEqual(claims('`supports pose estimation`'), (True, False))

    def test_negative_removal(self):
        for phrase in NOPOSE:
            self.assertEqual(claims(phrase), (False, True), phrase)

    def test_positive_templates(self):
        for phrase in POSE:
            self.assertEqual(claims(phrase), (True, False), phrase)

    def test_hyphens(self):
        self.assertEqual(claims('supports-pose-estimation'), (True, False))

    def test_contractions(self):
        self.assertEqual(claims("doesn't estimate poses"), (False, True))

    def test_paragraph_join(self):
        self.assertEqual(claims('supports pose\nestimation'), (True, False))
        self.assertEqual(claims('supports pose\n\nestimation'), (False, False))

    def test_longest(self):
        self.assertEqual(matches('body pose estimation support', reversed(POSE)), [(0,28)])

    def test_boundaries(self):
        self.assertEqual(claims('redetect posesx'), (False, False))

    def test_sorted_unique(self):
        for phrases in (POSE, NOPOSE):
            self.assertEqual(list(phrases), sorted(phrases, key=len, reverse=True))
            self.assertEqual(len(phrases),len(set(phrases)))


class EvidenceTests(unittest.TestCase):
    pass

POSITIVE = {
 'direct': 'import mediapipe\nmediapipe.solutions.pose.Pose()',
 'alias': 'import mediapipe as mp\nmp.solutions.pose.Pose()',
 'from_import': 'from mediapipe.solutions.pose import Pose\nPose()',
 'module_alias': 'from mediapipe.solutions import pose as p\np.Pose()',
 'with': 'from mediapipe.solutions.pose import Pose\nwith Pose() as p:\n p.process(image)',
 'attribute': 'from mediapipe.solutions.pose import Pose\nself.p = Pose()\nself.p.process(image)',
 'chained': 'from mediapipe.solutions.pose import Pose\nPose().process(image)',
 'bound_process': 'from mediapipe.solutions.pose import Pose\np=Pose()\np.process(image)',
 'annotated': 'from mediapipe.solutions.pose import Pose\np: object = Pose()\np.process(image)',
 'tasks_direct': 'import mediapipe as mp\nmp.tasks.vision.PoseLandmarker.create_from_options(options)',
 'tasks_from': 'from mediapipe.tasks.vision import PoseLandmarker as P\nP.create_from_options(options)',
 'tasks_construct': 'from mediapipe.tasks.vision import PoseLandmarker\nPoseLandmarker(options)',
}
for method in ('detect', 'detect_for_video', 'detect_async'):
 POSITIVE['bound_'+method]='from mediapipe.tasks.vision import PoseLandmarker as P\np=P.create_from_options(options)\np.'+method+'(image)'
NEGATIVE = {
 'bare_import':'import mediapipe',
 'image_open':'import cv2\ncv2.imread("image")\nfrom PIL import Image\nImage.open("image")',
 'camera':'import cv2\ncv2.VideoCapture(0).read()',
 'drawing':'import mediapipe as mp\nmp.solutions.drawing_utils.draw_landmarks(image, landmarks)',
 'face':'import mediapipe as mp\nmp.solutions.face_detection.FaceDetection()',
 'hand':'import mediapipe as mp\nmp.solutions.hands.Hands()',
 'yolo':'from ultralytics import YOLO\nYOLO("model")',
 'local_class':'from mediapipe.solutions.pose import Pose\nclass Pose: pass\nPose()',
 'local_function':'from mediapipe.tasks.vision import PoseLandmarker\ndef PoseLandmarker(): pass\nPoseLandmarker()',
 'shadow_module':'import mediapipe as mp\ndef mp(): pass\nmp.solutions.pose.Pose()',
 'unbound':'p.process(image)\np.detect(image)\np.detect_for_video(image)\np.detect_async(image)',
 'string':'s="mediapipe.solutions.pose.Pose() skeleton pose"',
 'subprocess':'import subprocess\nsubprocess.run(["pose", "detect"])',
 'syntax':'import mediapipe\nmediapipe.solutions.pose.Pose((',
 'other_provider':'import other\nother.pose.Pose()\nother.PoseLandmarker()',
}
def case(source, expected):
 def test(self): self.assertEqual(evidence(source), expected)
 return test
for name, source in POSITIVE.items(): setattr(EvidenceTests,'test_'+name,case(source, True))
for name, source in NEGATIVE.items(): setattr(EvidenceTests,'test_'+name,case(source, False))


class IntegrationTests(unittest.TestCase):
    def cli(self, *args):
        p=subprocess.run([sys.executable,'-m','pose_claim_audit',*map(str,args)],capture_output=True,text=True)
        return p

    def test_fixtures(self):
        for fixture,code,rule,severity in [('good',0,None,None),('bad',2,'documented-pose-claim-false','HIGH'),('testonly',0,'documented-pose-claim-false','MEDIUM'),('no-pose',2,'documented-no-pose-claim-false','HIGH'),('no-claim',0,None,None)]:
            p=self.cli(ROOT/'fixtures'/fixture,'--json'); self.assertEqual(p.returncode,code,p.stderr)
            data=json.loads(p.stdout); self.assertEqual(set(data),{'verdict','findings','files_scanned'})
            self.assertEqual(len(data['findings']),int(rule is not None))
            if rule: self.assertEqual((data['findings'][0]['rule'],data['findings'][0]['severity']),(rule,severity))
        self.assertEqual(self.cli(ROOT/'fixtures/testonly','--fail-on','MEDIUM').returncode,2)

    def test_ignore(self):
        self.assertEqual(audit(ROOT/'fixtures/bad',['README.*'])['findings'],[])

    def test_verbose(self):
        self.assertIn('Files scanned: 2',self.cli(ROOT/'fixtures/good','--verbose').stdout)

    def test_version(self):
        p=self.cli('--version'); self.assertEqual((p.returncode,p.stdout.strip()),(0,'0.1.0'))

    def test_invalid_root(self):
        self.assertEqual(self.cli(ROOT/'missing').returncode,1)
        self.assertEqual(self.cli(ROOT/'README.md').returncode,1)

    def test_usage(self):
        for args in [(),('--unknown',),('.', '--fail-on','LOW')]:
            self.assertEqual(self.cli(*args).returncode,1)

    def test_self(self):
        self.assertEqual(audit(ROOT)['findings'],[])

    def test_exclusions_symlinks_docs(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp); (d/'README.md').write_text('supports pose estimation')
            for component in ('fixtures','examples','docs','tests'):
                (d/component).mkdir(); (d/component/'source.py').write_text(POSITIVE['direct'])
            (d/'linked.py').symlink_to(d/'tests/source.py')
            (d/'linked_dir').symlink_to(d/'tests',target_is_directory=True)
            result=audit(d); self.assertEqual(result['findings'][0]['severity'],'MEDIUM')
            (d/'tests/source.py').unlink()
            self.assertEqual(audit(d)['findings'][0]['severity'],'HIGH')
            (d/'README.md').write_text('Utility')
            (d/'docs/note.md').write_text('supports pose estimation')
            self.assertEqual(len(audit(d)['findings']),1)

    def test_test_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp); (d/'README.md').write_text('supports pose estimation')
            for name in ('test_app.py','app_test.py'):
                f=d/name; f.write_text(POSITIVE['direct'])
                self.assertEqual(audit(d)['findings'][0]['severity'],'MEDIUM'); f.unlink()


if __name__ == '__main__':
    unittest.main()
