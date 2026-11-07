import java.awt.*;
import java.awt.geom.*;
import java.awt.image.BufferedImage;
import java.io.File;
import javax.imageio.ImageIO;

/** Draws the launcher icon and the Android TV home-screen banner (glowing ring + pulse line). */
public class Art {
    static final Color BG = new Color(0x0a0a0b), TRACK = new Color(0x27272b), GREEN = new Color(0x0ca30c), INK = new Color(0xf0efec);

    public static void main(String[] a) throws Exception {
        String res = a.length > 0 ? a[0] : "res";
        ImageIO.write(icon(192), "png", new File(res + "/drawable-xxhdpi/ic_launcher.png"));
        ImageIO.write(banner(320, 180), "png", new File(res + "/drawable-xhdpi/banner.png"));
    }

    static Graphics2D g(BufferedImage img) {
        Graphics2D g = img.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
        g.setRenderingHint(RenderingHints.KEY_STROKE_CONTROL, RenderingHints.VALUE_STROKE_PURE);
        g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
        return g;
    }

    static void ring(Graphics2D g, double cx, double cy, double r, double w) {
        g.setStroke(new BasicStroke((float) w, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
        g.setColor(TRACK);
        g.draw(new Ellipse2D.Double(cx - r, cy - r, 2 * r, 2 * r));
        for (int i = 6; i >= 1; i--) { // soft glow
            g.setStroke(new BasicStroke((float) (w + i * 3), BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
            g.setColor(new Color(12, 163, 12, 10));
            g.draw(new Arc2D.Double(cx - r, cy - r, 2 * r, 2 * r, 90, -252, Arc2D.OPEN));
        }
        g.setStroke(new BasicStroke((float) w, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
        g.setColor(GREEN);
        g.draw(new Arc2D.Double(cx - r, cy - r, 2 * r, 2 * r, 90, -252, Arc2D.OPEN));
    }

    static void pulse(Graphics2D g, double cx, double cy, double s, double w) {
        Path2D p = new Path2D.Double();
        p.moveTo(cx - 1.06 * s, cy + 0.04 * s);
        p.lineTo(cx - 0.55 * s, cy + 0.04 * s);
        p.lineTo(cx - 0.29 * s, cy - 0.56 * s);
        p.lineTo(cx + 0.17 * s, cy + 0.66 * s);
        p.lineTo(cx + 0.43 * s, cy + 0.04 * s);
        p.lineTo(cx + 1.04 * s, cy + 0.04 * s);
        g.setStroke(new BasicStroke((float) w, BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
        g.setColor(INK);
        g.draw(p);
    }

    static BufferedImage icon(int n) {
        BufferedImage img = new BufferedImage(n, n, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = g(img);
        g.setColor(BG);
        g.fill(new RoundRectangle2D.Double(0, 0, n, n, n * 0.22, n * 0.22));
        ring(g, n / 2.0, n / 2.0, n * 0.30, n * 0.065);
        pulse(g, n / 2.0, n / 2.0, n * 0.20, n * 0.05);
        g.dispose();
        return img;
    }

    static BufferedImage banner(int w, int h) {
        BufferedImage img = new BufferedImage(w, h, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = g(img);
        g.setColor(BG);
        g.fillRect(0, 0, w, h);
        g.setPaint(new RadialGradientPaint(new Point2D.Double(w * 0.25, -h * 0.2), w * 0.9f,
            new float[]{0f, 1f}, new Color[]{new Color(12, 163, 12, 45), new Color(10, 10, 11, 0)}));
        g.fillRect(0, 0, w, h);
        ring(g, h * 0.5, h * 0.5, h * 0.30, h * 0.06);
        pulse(g, h * 0.5, h * 0.5, h * 0.20, h * 0.045);
        g.setColor(INK);
        g.setFont(new Font("SansSerif", Font.BOLD, (int) (h * 0.19)));
        FontMetrics fm = g.getFontMetrics();
        String t = "VITALS";
        int x = (int) (h * 0.95);
        // manual letter spacing
        for (char c : t.toCharArray()) { g.drawString(String.valueOf(c), x, (int) (h * 0.555)); x += fm.charWidth(c) + (int) (h * 0.022); }
        g.setColor(new Color(0x898781));
        g.setFont(new Font("SansSerif", Font.PLAIN, (int) (h * 0.09)));
        g.drawString("Health & training", (int) (h * 0.97), (int) (h * 0.72));
        g.dispose();
        return img;
    }
}
