"""Patch StPageFlip 2.0.7 for natural touch on phones/tablets (RTL magazine).
1) The page follows the finger from the first touch (no 250 ms hold).
2) A quick flick completes the flip in the flick direction; a slow drag settles by whether it passed the middle of the page.
3) Portrait (single page): left half of the page turns BACK (= forward reading in our reversed RTL stack).
"""
import sys
src, out = sys.argv[1], sys.argv[2]
s = open(src, encoding='utf-8').read()
def rep(old, new):
    global s
    assert s.count(old) == 1, ('patch target not found', old[:60])
    s = s.replace(old, new)
rep('setTimeout(()=>{null!==this.touchPoint&&this.app.startUserTouch(i)},this.swipeTimeout)',
    'this.app.startUserTouch(i)')
rep('let s=!1;if(null!==this.touchPoint){const t=i.x-this.touchPoint.point.x,e=Math.abs(i.y-this.touchPoint.point.y);Math.abs(t)>this.swipeDistance&&e<2*this.swipeDistance&&Date.now()-this.touchPoint.time<this.swipeTimeout&&(t>0?this.app.flipPrev(this.touchPoint.point.y<this.app.getRender().getRect().height/2?"top":"bottom"):this.app.flipNext(this.touchPoint.point.y<this.app.getRender().getRect().height/2?"top":"bottom"),s=!0),this.touchPoint=null}this.app.userStop(i,s)',
    'let f=0;if(null!==this.touchPoint){const t=i.x-(this.lastTouch||this.touchPoint).point.x,dt=Date.now()-(this.lastTouch||this.touchPoint).time,T=i.x-this.touchPoint.point.x;(Math.abs(T)>this.swipeDistance&&Date.now()-this.touchPoint.time<350||Math.abs(t)/Math.max(dt,1)>.45)&&(f=(Math.abs(t)>2?t:T)>0?1:-1),this.touchPoint=null,this.lastTouch=null}this.app.userStop(i,!1,f)')
# remember recent touch position for velocity
rep('this.onTouchMove=t=>{if(t.changedTouches.length>0){const e=t.changedTouches[0],i=this.getMousePos(e.clientX,e.clientY);',
    'this.onTouchMove=t=>{if(t.changedTouches.length>0){const e=t.changedTouches[0],i=this.getMousePos(e.clientX,e.clientY);{const n=Date.now();(!this._tp||n-this._tp.time>60)&&(this.lastTouch=this._tp||null,this._tp={point:i,time:n})}')
rep('userStop(t,e=!1){this.isUserTouch&&(this.isUserTouch=!1,e||(this.isUserMove?this.flipController.stopMove():this.flipController.flip(t)))}',
    'userStop(t,e=!1,f=0){this.isUserTouch&&(this.isUserTouch=!1,e||(this.isUserMove?this.flipController.stopMove(f):this.flipController.flip(t)))}')
rep('stopMove(){if(null===this.calc)return;const t=this.calc.getPosition(),e=this.getBoundsRect(),i="bottom"===this.calc.getCorner()?e.height:0;t.x<=0?',
    'stopMove(f=0){if(null===this.calc)return;const t=this.calc.getPosition(),e=this.getBoundsRect(),i="bottom"===this.calc.getCorner()?e.height:0,d=this.calc.getDirection(),P="portrait"===this.render.getOrientation()?(0===d?e.pageWidth/2:-e.pageWidth/2):0;(0!==f?0===d?f<0:f>0:t.x<=P)?')
rep('if(t.x-e.pageWidth<=e.width/5)return 1', 'if(t.x-e.pageWidth<=e.pageWidth/2)return 1')
open(out, 'w', encoding='utf-8').write(s)
print('patched ok')
