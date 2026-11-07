import java.awt.*;
import java.awt.geom.*;
import java.awt.image.BufferedImage;
import java.io.File;
import javax.imageio.ImageIO;

/** Draws the Vitals brand assets for the TV app: launcher icon, home-screen banner and boot-screen logo.
 *  Geometry matches the web app's SVG (100-unit cap height, split-stroke V). */
public class Art {
    static final Color BG = new Color(0x000000), INK = new Color(0xf0efec);

    public static void main(String[] a) throws Exception {
        String res = a.length > 0 ? a[0] : "res";
        new File(res + "/drawable-xxhdpi").mkdirs();
        new File(res + "/drawable-xhdpi").mkdirs();
        ImageIO.write(icon(192), "png", new File(res + "/drawable-xxhdpi/ic_launcher.png"));
        ImageIO.write(banner(320, 180), "png", new File(res + "/drawable-xhdpi/banner.png"));
        ImageIO.write(splashLogo(), "png", new File(res + "/drawable-xhdpi/splash_logo.png"));
    }

    static Graphics2D g(BufferedImage img) {
        Graphics2D g = img.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
        g.setRenderingHint(RenderingHints.KEY_STROKE_CONTROL, RenderingHints.VALUE_STROKE_PURE);
        g.setRenderingHint(RenderingHints.KEY_RENDERING, RenderingHints.VALUE_RENDER_QUALITY);
        return g;
    }

    static Path2D poly(double... xy) {
        Path2D p = new Path2D.Double();
        p.moveTo(xy[0], xy[1]);
        for (int i = 2; i < xy.length; i += 2) p.lineTo(xy[i], xy[i + 1]);
        p.closePath();
        return p;
    }

    /** Split V: two slashes that don't meet (100-unit tall, 66 wide). */
    static void glyphV(Graphics2D g) { g.fill(poly(0, 0, 10, 0, 31, 100, 21, 100)); g.fill(poly(56, 0, 66, 0, 45, 100, 35, 100)); }
    static void glyphA(Graphics2D g) { g.fill(poly(21, 0, 31, 0, 10, 100, 0, 100)); g.fill(poly(35, 0, 45, 0, 66, 100, 56, 100)); }

    /** VITALS wordmark in a 400 x 100 box at the current transform. */
    static void wordmark(Graphics2D g) {
        AffineTransform t0 = g.getTransform();
        glyphV(g);
        g.translate(88, 0); g.fill(new Rectangle2D.Double(0, 0, 9.6, 100));
        g.setTransform(t0); g.translate(119.5, 0); g.fill(poly(0, 0, 56, 0, 56, 9.6, 32.8, 9.6, 32.8, 100, 23.2, 100, 23.2, 9.6, 0, 9.6));
        g.setTransform(t0); g.translate(192, 0); glyphA(g);
        g.setTransform(t0); g.translate(281.5, 0); g.fill(poly(0, 0, 9.6, 0, 9.6, 90.4, 48, 90.4, 48, 100, 0, 100));
        g.setTransform(t0); g.translate(347.5, 0);
        Path2D s = new Path2D.Double();
        s.moveTo(51, 15);
        s.curveTo(45.5, 8, 37, 4.8, 27, 4.8);
        s.curveTo(13.5, 4.8, 4.8, 12.5, 4.8, 24.5);
        s.curveTo(4.8, 52, 47.2, 46, 47.2, 75);
        s.curveTo(47.2, 87.5, 38.5, 95.2, 25, 95.2);
        s.curveTo(14.5, 95.2, 6, 90.5, 1, 82);
        g.setStroke(new BasicStroke(9.6f, BasicStroke.CAP_BUTT, BasicStroke.JOIN_MITER));
        g.draw(s);
        g.setTransform(t0);
    }

    /** Ring + split V in a 100 x 100 box at the current transform. */
    static void mark(Graphics2D g, double ringR, double ringW) {
        AffineTransform t0 = g.getTransform();
        g.setStroke(new BasicStroke((float) ringW));
        g.draw(new Ellipse2D.Double(50 - ringR, 50 - ringR, ringR * 2, ringR * 2));
        g.translate(36.8, 31); g.scale(0.4, 0.4); glyphV(g);
        g.setTransform(t0);
    }

    static BufferedImage icon(int n) {
        BufferedImage img = new BufferedImage(n, n, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = g(img);
        g.setColor(BG); g.fill(new RoundRectangle2D.Double(0, 0, n, n, n * 0.22, n * 0.22));
        g.setColor(INK); g.scale(n / 100.0, n / 100.0); mark(g, 33, 4.4);
        g.dispose();
        return img;
    }

    static BufferedImage banner(int w, int h) {
        BufferedImage img = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = g(img);
        g.setColor(BG); g.fillRect(0, 0, w, h);
        g.setColor(INK);
        AffineTransform t0 = g.getTransform();
        double ms = h * 0.5 / 100.0;                        // mark: half the banner height
        g.translate(h * 0.2, (h - 100 * ms) / 2); g.scale(ms, ms); mark(g, 44, 5);
        g.setTransform(t0);
        double ws = h * 0.15 / 100.0;                       // wordmark cap height 15% of banner
        g.translate(h * 0.2 + 100 * ms + h * 0.15, (h - 100 * ws) / 2); g.scale(ws, ws); wordmark(g);
        g.dispose();
        return img;
    }

    /** Boot-screen logo (mark above wordmark), shown by the window background while the WebView starts. */
    static BufferedImage splashLogo() {
        int w = 360, h = 300;
        BufferedImage img = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = g(img);
        g.setColor(INK);
        AffineTransform t0 = g.getTransform();
        double ms = 1.5;
        g.translate((w - 100 * ms) / 2, 10); g.scale(ms, ms); mark(g, 44, 5);
        g.setTransform(t0);
        double ws = 0.42;
        g.translate((w - 400 * ws) / 2, 10 + 100 * ms + 50); g.scale(ws, ws); wordmark(g);
        g.dispose();
        return img;
    }
}
