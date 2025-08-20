class Point {
  let x: integer;
  let y: integer;
  function setX(v: integer): integer { this.x = v; return this.x; }
  function getX(): integer { return this.x; }
}
let p: Point = new Point();
p.setX(3);
let t: integer = p.getX();
