import math,struct,unittest
import numpy as np
from scipy.spatial.transform import Rotation as Rot
import asset_localization as al

class Geometry(unittest.TestCase):
 def test_cube_face_round_trip_and_orientation(self):
  rng=np.random.default_rng(1)
  for view in al.FACES:
   u,v=rng.uniform(5,763,50),rng.uniform(5,763,50);b=al.face_to_cam(u,v,768,view);u2,v2,ok=al.cam_to_face(b,768,view)
   self.assertTrue(ok.all());np.testing.assert_allclose(u2,u,atol=1e-6);np.testing.assert_allclose(v2,v,atol=1e-6)
  # front-face centre is the OpenSfM optical axis; right face centre is +x; 'up' is -y (camera y points down)
  np.testing.assert_allclose(al.face_to_cam(384,384,768,'front'),[0,0,1],atol=1e-9)
  np.testing.assert_allclose(al.face_to_cam(384,384,768,'right'),[1,0,0],atol=1e-9)
  np.testing.assert_allclose(al.face_to_cam(384,384,768,'up'),[0,-1,0],atol=1e-9)
 def test_flat_round_trip_with_distortion(self):
  for kind in ['perspective','fisheye']:
   u,v=np.array([100.,1024,1900]),np.array([80.,576,1100]);b=al.flat_to_cam(u,v,2048,1152,[.8,-.05,.01],kind);u2,v2,ok=al.cam_to_flat(b,2048,1152,[.8,-.05,.01],kind)
   np.testing.assert_allclose(u2,u,atol=1e-3);np.testing.assert_allclose(v2,v,atol=1e-3)
 def test_multiview_solve_recovers_point_and_rejects_behind(self):
  X=np.array([10.,20.]);cams=[(0,0),(3,1),(6,2),(9,3)]
  obs=[(cx,cy,math.atan2(X[0]-cx,X[1]-cy),math.hypot(X[0]-cx,X[1]-cy)*1.1,.3) for cx,cy in cams]
  P,cov,chi2,m,res,ahead=al.solve(obs,math.radians(.5));self.assertTrue(ahead);self.assertLess(np.hypot(*(P-X)),.15)
  P,*_ ,ahead=al.solve(obs,math.radians(.5),use_range=False);self.assertLess(np.hypot(*(P-X)),1e-3)
  flipped=[(cx,cy,a+math.pi,r,s) for cx,cy,a,r,s in obs[:2]]
  P,cov,chi2,m,res,ahead=al.solve(flipped,math.radians(.5));self.assertTrue((not ahead) or np.max(np.abs(res))>3)  # association gate rejects it
 def test_foreground_depth_ignores_background(self):
  r,s,n=al.foreground_range(np.array([12.1,12.3,12.2,30,31,45,2.0]));self.assertAlmostEqual(r,12.2,places=5);self.assertEqual(n,3)
 def test_mesh_decode_scale_and_placeholder(self):
  pts=[(.1,.1,.1)]*8+[(2.,0,10.),(-3.,1.,20.)];blob=b''.join(b'\x0d'+struct.pack('<f',x) for p in pts for x in p)+b'\x10\x05'
  v=al.decode_mesh(blob,2.0);np.testing.assert_allclose(v,[[1,0,5],[-1.5,.5,10]],atol=1e-6)
 def test_ground_plane_and_contact_range(self):
  # level camera 2.2 m above a flat road, looking north; hydrant base 15 m ahead.
  R=Rot.from_euler('x',90,degrees=True).as_matrix()   # world ENU -> camera (z forward = north, y down)
  rng=np.random.default_rng(0);e,n=rng.uniform(-15,15,300),rng.uniform(-15,15,300);pts=np.c_[e,n,np.full(300,-2.2)]@R.T
  g=al.fit_ground(pts,R);self.assertAlmostEqual(g['height_m'],2.2,places=3)
  pose={'computed_geometry':{'coordinates':[-71.29,42.30]},'computed_altitude':50,'computed_rotation':list(Rot.from_matrix(R).as_rotvec()),'camera_type':'spherical'}
  cam=al.Camera('t','i',pose,None,g)
  base=np.array([0,15.,-2.2])@R.T;base/=np.linalg.norm(base);top=np.array([0,15.,-2.2+.78])@R.T;top/=np.linalg.norm(top)
  (ub,),(vb,),_=al.cam_to_face(base[None],768,'front');(ut,),(vt,),_=al.cam_to_face(top[None],768,'front')
  az,el,r,s,cues,flags=al.observation_geometry(cam,'fire hydrant',{'xyxy':[ub-6,vt,ub+6,vb],'width':768,'height':768,'view':'front'},{})
  self.assertAlmostEqual(cues['ground']['range_m'],15,delta=.05);self.assertAlmostEqual(cues['size']['range_m'],15,delta=.4);self.assertLess(abs(((az+180)%360)-180),.3)

if __name__=='__main__':unittest.main()
